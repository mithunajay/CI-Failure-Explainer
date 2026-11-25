import unittest

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from ci_explainer.auth import (
    authenticate,
    change_password,
    create_account,
    ensure_bootstrap_admin,
    request_email_verification,
    request_password_reset,
    reset_password_with_otp,
    set_account_active,
    verify_password,
    verify_email_otp,
)
from ci_explainer.database import Base, User


class AuthTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(self.engine)
        self.session = Session(self.engine)

    def tearDown(self):
        self.session.close()
        self.engine.dispose()

    def test_password_hash_is_salted_and_verifiable(self):
        user_id = create_account(
            self.session, "engineer", "correct horse battery staple", "engineer@example.com"
        )
        user = self.session.get(User, user_id)
        self.assertNotEqual(user.password_salt, "0" * 32)
        self.assertTrue(verify_password("correct horse battery staple", user))
        self.assertFalse(verify_password("wrong password", user))

    def test_bootstrap_admin_and_authentication(self):
        self.assertTrue(
            ensure_bootstrap_admin(
                self.session, "Master.Admin", "a sufficiently long password",
                "master@example.com",
            )
        )
        user = authenticate(
            self.session, "master.admin", "a sufficiently long password"
        )
        self.assertEqual(user["role"], "admin")
        self.assertIsNone(
            authenticate(self.session, "master.admin", "not the password")
        )

    def test_empty_database_requires_configured_admin(self):
        self.assertFalse(ensure_bootstrap_admin(self.session, "", "", ""))

    def test_existing_admin_requires_verified_email(self):
        create_account(
            self.session, "master", "a sufficiently long password",
            "master@example.com", role="admin",
        )
        self.assertFalse(
            ensure_bootstrap_admin(self.session, "master", "a sufficiently long password", "")
        )
        self.assertTrue(
            ensure_bootstrap_admin(
                self.session, "master", "a sufficiently long password", "master@example.com"
            )
        )
        self.assertTrue(
            authenticate(self.session, "master", "a sufficiently long password")
        )

    def test_admin_created_accounts_can_be_disabled(self):
        admin_id = create_account(
            self.session, "master", "a sufficiently long password",
            "master@example.com", role="admin", email_verified=True,
        )
        user_id = create_account(
            self.session, "engineer", "another long password", "engineer@example.com",
            email_verified=True,
        )
        self.assertEqual(
            authenticate(self.session, "engineer", "another long password")["role"],
            "user",
        )
        set_account_active(self.session, user_id, False, admin_id)
        self.assertIsNone(
            authenticate(self.session, "engineer", "another long password")
        )

    def test_password_change_checks_current_password(self):
        user_id = create_account(
            self.session, "engineer", "an old long password", "engineer@example.com",
            email_verified=True,
        )
        self.assertFalse(
            change_password(
                self.session, user_id, "incorrect current password", "a new long password"
            )
        )
        self.assertTrue(
            change_password(
                self.session, user_id, "an old long password", "a new long password"
            )
        )
        self.assertIsNotNone(
            authenticate(self.session, "engineer", "a new long password")
        )

    def test_last_active_admin_cannot_be_deactivated(self):
        admin_id = create_account(
            self.session, "master", "a sufficiently long password",
            "master@example.com", role="admin", email_verified=True,
        )
        with self.assertRaisesRegex(ValueError, "own admin account"):
            set_account_active(self.session, admin_id, False, admin_id)

    def test_registration_requires_email_verification_before_login(self):
        create_account(
            self.session, "newuser", "a sufficiently long password", "new@example.com"
        )
        sent = []
        self.assertTrue(request_email_verification(
            self.session, "new@example.com", "x" * 40,
            lambda email, code, purpose: sent.append((email, code, purpose)),
        ))
        self.assertIsNone(authenticate(self.session, "newuser", "a sufficiently long password"))
        email, code, purpose = sent[0]
        self.assertEqual((email, purpose), ("new@example.com", "verify"))
        self.assertTrue(verify_email_otp(self.session, email, code, "x" * 40))
        self.assertIsNotNone(authenticate(self.session, "newuser", "a sufficiently long password"))
        self.assertFalse(verify_email_otp(self.session, email, code, "x" * 40))

    def test_password_recovery_sends_otp_and_changes_password(self):
        create_account(
            self.session, "recover", "an old long password", "recover@example.com",
            email_verified=True,
        )
        sent = []
        self.assertTrue(request_password_reset(
            self.session, "recover@example.com", "y" * 40,
            lambda email, code, purpose: sent.append((email, code, purpose)),
        ))
        self.assertFalse(request_password_reset(
            self.session, "recover@example.com", "y" * 40,
            lambda email, code, purpose: sent.append((email, code, purpose)),
        ))
        email, code, purpose = sent[0]
        self.assertEqual(purpose, "reset")
        self.assertFalse(reset_password_with_otp(
            self.session, email, f"{(int(code) + 1) % 1_000_000:06d}",
            "a new long password", "y" * 40,
        ))
        self.assertTrue(reset_password_with_otp(
            self.session, email, code, "a new long password", "y" * 40,
        ))
        self.assertIsNotNone(authenticate(self.session, "recover", "a new long password"))
        self.assertFalse(reset_password_with_otp(
            self.session, email, code, "a third long password", "y" * 40,
        ))

    def test_recovery_request_does_not_send_for_unknown_email(self):
        sent = []
        self.assertFalse(request_password_reset(
            self.session, "unknown@example.com", "z" * 40,
            lambda email, code, purpose: sent.append(code),
        ))
        self.assertEqual(sent, [])

    def test_otp_is_invalidated_after_five_wrong_attempts(self):
        create_account(
            self.session, "locked", "a sufficiently long password", "locked@example.com",
            email_verified=True,
        )
        sent = []
        request_password_reset(
            self.session, "locked@example.com", "q" * 40,
            lambda email, code, purpose: sent.append(code),
        )
        correct_code = sent[0]
        wrong_code = f"{(int(correct_code) + 1) % 1_000_000:06d}"
        for _ in range(5):
            self.assertFalse(reset_password_with_otp(
                self.session, "locked@example.com", wrong_code,
                "a replacement password", "q" * 40,
            ))
        self.assertFalse(reset_password_with_otp(
            self.session, "locked@example.com", correct_code,
            "a replacement password", "q" * 40,
        ))

    def test_expired_otp_is_rejected(self):
        from datetime import datetime, timedelta, timezone

        from ci_explainer.database import User

        create_account(
            self.session, "expired", "a sufficiently long password", "expired@example.com",
            email_verified=True,
        )
        sent = []
        request_password_reset(
            self.session, "expired@example.com", "r" * 40,
            lambda email, code, purpose: sent.append(code),
        )
        user = self.session.query(User).filter_by(email="expired@example.com").one()
        user.otp_expires_at = (
            datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(seconds=1)
        )
        self.session.commit()
        self.assertFalse(reset_password_with_otp(
            self.session, "expired@example.com", sent[0],
            "a replacement password", "r" * 40,
        ))


if __name__ == "__main__":
    unittest.main()
