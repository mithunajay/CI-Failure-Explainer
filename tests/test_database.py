import unittest

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import Session

from ci_explainer.auth import create_account
from ci_explainer.database import (
    Analysis,
    Base,
    initialize_database,
    list_analyses,
    save_analysis,
)


class DatabaseTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite:///:memory:")
        initialize_database(self.engine)
        self.session = Session(self.engine)
        self.user_one_id = create_account(
            self.session, "engineerone", "a sufficiently long password",
            "one@example.com", email_verified=True,
        )
        self.user_two_id = create_account(
            self.session, "engineertwo", "another sufficiently long password",
            "two@example.com", email_verified=True,
        )

    def tearDown(self):
        self.session.close()
        self.engine.dispose()

    def test_initialization_adds_email_and_otp_columns_to_existing_users(self):
        legacy_engine = create_engine("sqlite:///:memory:")
        with legacy_engine.begin() as connection:
            connection.execute(text(
                "CREATE TABLE users (id INTEGER PRIMARY KEY, username VARCHAR(32) NOT NULL, "
                "password_salt VARCHAR(32) NOT NULL, password_hash VARCHAR(64) NOT NULL, "
                "role VARCHAR(16) NOT NULL, active BOOLEAN NOT NULL)"
            ))
        initialize_database(legacy_engine)
        columns = {column["name"] for column in inspect(legacy_engine).get_columns("users")}
        self.assertTrue({
            "email", "email_verified", "otp_hash", "otp_purpose",
            "otp_expires_at", "otp_requested_at", "otp_attempts",
        }.issubset(columns))
        indexes = {index["name"] for index in inspect(legacy_engine).get_indexes("users")}
        self.assertIn("uq_users_email", indexes)
        legacy_engine.dispose()

    @staticmethod
    def explanation():
        return {
            "category": "unknown",
            "summary": "A test explanation",
            "root_cause": "Unknown",
            "evidence": [],
            "suggested_fix": ["Review the failure manually."],
            "confidence": "low",
            "source": "rules",
            "injection_flags": [],
            "redactions": 1,
            "errors": [],
            "input_tokens": 0,
            "output_tokens": 0,
            "latency_s": 0,
        }

    def test_saves_only_cleaned_redacted_log_for_owner(self):
        user = {"id": self.user_one_id, "username": "engineerone"}
        save_analysis(
            self.session,
            user,
            "ERROR: token=very-secret-value",
            self.explanation(),
        )
        saved = self.session.query(Analysis).one()
        self.assertNotIn("very-secret-value", saved.log)
        self.assertIn("[REDACTED]", saved.log)
        self.assertEqual(saved.user_id, self.user_one_id)

    def test_user_history_filters_to_owner_and_admin_history_can_be_global(self):
        save_analysis(
            self.session,
            {"id": self.user_one_id, "username": "engineerone"},
            "first log",
            self.explanation(),
        )
        save_analysis(
            self.session,
            {"id": self.user_two_id, "username": "engineertwo"},
            "second log",
            self.explanation(),
        )
        private_records = list_analyses(self.session, self.user_one_id)
        all_records = list_analyses(self.session)
        self.assertEqual([r.username for r in private_records], ["engineerone"])
        self.assertEqual(len(all_records), 2)


if __name__ == "__main__":
    unittest.main()
