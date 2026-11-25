"""Password and account helpers for the local web application."""
from __future__ import annotations

import hashlib
import hmac
import re
import secrets

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .database import User

PASSWORD_ITERATIONS = 600_000
USERNAME_RE = re.compile(r"^[a-zA-Z0-9._-]{3,32}$")
_DUMMY_SALT = "0" * 32


def normalize_username(username: str) -> str:
    return username.strip().casefold()


def validate_credentials(username: str, password: str) -> None:
    if not USERNAME_RE.fullmatch(username.strip()):
        raise ValueError("Username must be 3-32 characters: letters, numbers, '.', '_' or '-'.")
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
    session: Session, username: str, password: str, role: str = "user"
) -> int:
    validate_credentials(username, password)
    if role not in {"admin", "user"}:
        raise ValueError("Account role must be admin or user.")
    record = User(
        username=normalize_username(username),
        role=role,
        active=True,
        **password_fields(password),
    )
    session.add(record)
    try:
        session.commit()
    except IntegrityError as error:
        session.rollback()
        raise ValueError("That username is already in use.") from error
    return record.id


def ensure_bootstrap_admin(session: Session, username: str, password: str) -> bool:
    existing = session.scalar(select(User.id).where(User.role == "admin").limit(1))
    if existing is not None:
        return True
    if not username or not password:
        return False
    create_account(session, username, password, role="admin")
    return True


def authenticate(session: Session, username: str, password: str) -> dict | None:
    normalized = normalize_username(username)
    record = session.scalar(select(User).where(User.username == normalized))
    valid_password = verify_password(password, record)
    if not record or not record.active or not valid_password:
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
