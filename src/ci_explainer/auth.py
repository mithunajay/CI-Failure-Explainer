"""Password and account helpers for the local web application."""
from __future__ import annotations

import hashlib
import hmac
import re
import secrets
from datetime import datetime, timedelta, timezone
from email.utils import parseaddr

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .database import User
from .email_otp import send_otp_email

PASSWORD_ITERATIONS = 600_000
USERNAME_RE = re.compile(r"^[a-zA-Z0-9._-]{3,32}$")
EMAIL_RE = re.compile(r"^[^@\s]{1,64}@[^@\s.]+(?:\.[^@\s.]+)+$")
_DUMMY_SALT = "0" * 32
OTP_LIFETIME = timedelta(minutes=10)
OTP_RESEND_DELAY = timedelta(seconds=60)
OTP_MAX_ATTEMPTS = 5


def normalize_username(username: str) -> str:
    return username.strip().casefold()


def normalize_email(email: str) -> str:
    return email.strip().casefold()


def validate_email(email: str) -> None:
    normalized = normalize_email(email)
    if len(normalized) > 254 or not EMAIL_RE.fullmatch(normalized):
        raise ValueError("Enter a valid email address.")
    if parseaddr(normalized)[1] != normalized:
        raise ValueError("Enter a valid email address.")


def validate_credentials(username: str, password: str) -> None:
    if not USERNAME_RE.fullmatch(username.strip()):
        raise ValueError("Username must be 3-32 characters: letters, numbers, '.', '_' or '-'.")
    validate_password(password)


def validate_password(password: str) -> None:
    if len(password) < 12:
        raise ValueError("Password must be at least 12 characters.")
    if len(password) > 1024:
        raise ValueError("Password must not exceed 1024 characters.")


def _derive(password: str, salt: str) -> str:
    return hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), bytes.fromhex(salt), PASSWORD_ITERATIONS
    ).hex()


def password_fields(password: str) -> dict[str, str]:
    salt = secrets.token_hex(16)
    return {"password_salt": salt, "password_hash": _derive(password, salt)}


def verify_password(password: str, user: User | None) -> bool:
    salt = user.password_salt if user else _DUMMY_SALT
    expected = user.password_hash if user else ""
    actual = _derive(password[:1024], salt)
    return bool(expected) and hmac.compare_digest(actual, expected)


def create_account(
    session: Session,
    username: str,
    password: str,
    email: str,
    role: str = "user",
    email_verified: bool = False,
) -> int:
    validate_credentials(username, password)
    validate_email(email)
    if role not in {"admin", "user"}:
        raise ValueError("Account role must be admin or user.")
    record = User(
        username=normalize_username(username),
        email=normalize_email(email),
        email_verified=email_verified,
        role=role,
        active=True,
        **password_fields(password),
    )
    session.add(record)
    try:
        session.commit()
    except IntegrityError as error:
        session.rollback()
        raise ValueError("That username or email is already in use.") from error
    return record.id


def ensure_bootstrap_admin(
    session: Session, username: str, password: str, email: str
) -> bool:
    existing = session.scalar(select(User).where(User.role == "admin").limit(1))
    if existing is not None:
        if not existing.email and email:
            validate_email(email)
            existing.email = normalize_email(email)
            existing.email_verified = True
            session.commit()
        elif not existing.email:
            return False
        elif (
            email
            and existing.email == normalize_email(email)
            and not existing.email_verified
        ):
            existing.email_verified = True
            session.commit()
        return bool(existing.email and existing.email_verified)
    if not username or not password or not email:
        return False
    create_account(
        session, username, password, email, role="admin", email_verified=True
    )
    return True


def authenticate(session: Session, username: str, password: str) -> dict | None:
    normalized = normalize_username(username)
    record = session.scalar(select(User).where(User.username == normalized))
    valid_password = verify_password(password, record)
    if not record or not record.active or not record.email_verified or not valid_password:
        return None
    return {
        "id": record.id,
        "username": record.username,
        "role": record.role,
    }


def change_password(
    session: Session, user_id: int, current_password: str, new_password: str
) -> bool:
    record = session.get(User, user_id)
    if not record or not record.active or not verify_password(current_password, record):
        return False
    validate_credentials(record.username, new_password)
    fields = password_fields(new_password)
    record.password_salt = fields["password_salt"]
    record.password_hash = fields["password_hash"]
    session.commit()
    return True


def reset_password(session: Session, user_id: int, new_password: str) -> bool:
    record = session.get(User, user_id)
    if not record or not record.active:
        return False
    validate_credentials(record.username, new_password)
    fields = password_fields(new_password)
    record.password_salt = fields["password_salt"]
    record.password_hash = fields["password_hash"]
    session.commit()
    return True


def _otp_digest(code: str, secret: str) -> str:
    if len(secret) < 32:
        raise RuntimeError("Set APP_OTP_SECRET to a random value of at least 32 characters in .env.")
    return hmac.new(secret.encode("utf-8"), code.encode("ascii"), hashlib.sha256).hexdigest()


def _clear_otp(user: User) -> None:
    user.otp_hash = None
    user.otp_purpose = None
    user.otp_expires_at = None
    user.otp_attempts = 0


def _issue_otp(
    session: Session,
    record: User,
    purpose: str,
    secret: str,
    email_sender=send_otp_email,
) -> bool:
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    requested_at = record.otp_requested_at
    if requested_at:
        if requested_at.tzinfo is not None:
            requested_at = requested_at.astimezone(timezone.utc).replace(tzinfo=None)
        if now - requested_at < OTP_RESEND_DELAY:
            return False

    code = f"{secrets.randbelow(1_000_000):06d}"
    record.otp_hash = _otp_digest(code, secret)
    record.otp_purpose = purpose
    record.otp_expires_at = now + OTP_LIFETIME
    record.otp_requested_at = now
    record.otp_attempts = 0
    session.commit()
    try:
        email_sender(record.email, code, purpose)
    except RuntimeError:
        _clear_otp(record)
        record.otp_requested_at = None
        session.commit()
        raise
    return True


def request_email_verification(
    session: Session, email: str, secret: str, email_sender=send_otp_email
) -> bool:
    record = session.scalar(
        select(User).where(User.email == normalize_email(email))
    )
    if not record or record.email_verified or not record.active:
        return False
    return _issue_otp(session, record, "verify", secret, email_sender)


def request_password_reset(
    session: Session, email: str, secret: str, email_sender=send_otp_email
) -> bool:
    record = session.scalar(
        select(User).where(User.email == normalize_email(email))
    )
    if not record or not record.email_verified or not record.active:
        return False
    return _issue_otp(session, record, "reset", secret, email_sender)


def _check_otp(
    session: Session, email: str, code: str, purpose: str, secret: str
) -> User | None:
    normalized = normalize_email(email)
    record = session.scalar(select(User).where(User.email == normalized))
    if (
        not record
        or not record.active
        or record.otp_purpose != purpose
        or not record.otp_hash
        or not record.otp_expires_at
    ):
        return None

    now = datetime.now(timezone.utc).replace(tzinfo=None)
    expires_at = record.otp_expires_at
    if expires_at.tzinfo is not None:
        expires_at = expires_at.astimezone(timezone.utc).replace(tzinfo=None)
    if expires_at <= now or record.otp_attempts >= OTP_MAX_ATTEMPTS:
        _clear_otp(record)
        session.commit()
        return None

    if not re.fullmatch(r"\d{6}", code or "") or not hmac.compare_digest(
        record.otp_hash, _otp_digest(code, secret)
    ):
        record.otp_attempts += 1
        if record.otp_attempts >= OTP_MAX_ATTEMPTS:
            _clear_otp(record)
        session.commit()
        return None
    return record


def verify_email_otp(session: Session, email: str, code: str, secret: str) -> bool:
    record = _check_otp(session, email, code, "verify", secret)
    if not record:
        return False
    record.email_verified = True
    _clear_otp(record)
    session.commit()
    return True


def reset_password_with_otp(
    session: Session,
    email: str,
    code: str,
    new_password: str,
    secret: str,
) -> bool:
    validate_email(email)
    validate_password(new_password)
    record = _check_otp(session, email, code, "reset", secret)
    if not record:
        return False
    fields = password_fields(new_password)
    record.password_salt = fields["password_salt"]
    record.password_hash = fields["password_hash"]
    _clear_otp(record)
    session.commit()
    return True


def set_account_active(
    session: Session, user_id: int, active: bool, actor_id: int
) -> bool:
    record = session.get(User, user_id)
    if not record:
        return False
    if not active and record.role == "admin":
        if record.id == actor_id:
            raise ValueError("You cannot deactivate your own admin account.")
        active_admins = session.scalar(
            select(func.count()).select_from(User).where(
                User.role == "admin",
                User.active.is_(True),
                User.id != user_id,
            )
        )
        if active_admins == 0:
            raise ValueError("The last active admin account cannot be deactivated.")
    record.active = active
    session.commit()
    return True
