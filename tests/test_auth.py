import unittest

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from ci_explainer.auth import (
    authenticate,
    change_password,
    create_account,
    ensure_bootstrap_admin,
    set_account_active,
    verify_password,
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
            self.session, "engineer", "correct horse battery staple"
        )
        user = self.session.get(User, user_id)
        self.assertNotEqual(user.password_salt, "0" * 32)
        self.assertTrue(verify_password("correct horse battery staple", user))
        self.assertFalse(verify_password("wrong password", user))

    def test_bootstrap_admin_and_authentication(self):
        self.assertTrue(
            ensure_bootstrap_admin(
                self.session, "Master.Admin", "a sufficiently long password"
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
        self.assertFalse(ensure_bootstrap_admin(self.session, "", ""))

    def test_admin_created_accounts_can_be_disabled(self):
        admin_id = create_account(
            self.session, "master", "a sufficiently long password", role="admin"
        )
        user_id = create_account(self.session, "engineer", "another long password")
        self.assertEqual(
            authenticate(self.session, "engineer", "another long password")["role"],
            "user",
        )
        set_account_active(self.session, user_id, False, admin_id)
        self.assertIsNone(
            authenticate(self.session, "engineer", "another long password")
        )

    def test_password_change_checks_current_password(self):
        user_id = create_account(self.session, "engineer", "an old long password")
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
            self.session, "master", "a sufficiently long password", role="admin"
        )
        with self.assertRaisesRegex(ValueError, "own admin account"):
            set_account_active(self.session, admin_id, False, admin_id)


if __name__ == "__main__":
    unittest.main()
