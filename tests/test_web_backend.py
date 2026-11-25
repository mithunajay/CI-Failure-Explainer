import os
import unittest
from unittest.mock import patch

from ci_explainer.llm import FakeClient
from ci_explainer.web_backend import explain_log


class WebBackendTests(unittest.TestCase):
    def test_rules_only_explains_log_without_api_key(self):
        with patch.dict(os.environ, {}, clear=True):
            result = explain_log(
                "ERROR: Could not find a version that satisfies the requirement fastapi==9.9.9",
                use_model=False,
            )
        self.assertEqual(result.source, "rules")
        self.assertEqual(result.category, "dependency_install")

    def test_empty_log_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "Paste a CI log"):
            explain_log("  \n", use_model=False)

    def test_model_mode_requires_api_key(self):
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaisesRegex(RuntimeError, "ANTHROPIC_API_KEY"):
                explain_log("A failing log", use_model=True)

    def test_model_explanation_uses_existing_guarded_pipeline(self):
        raw_log = "ERROR: Could not find a version that satisfies the requirement fastapi==9.9.9"
        response = (
            '{"category":"dependency_install","summary":"A dependency version is unavailable.",'
            '"root_cause":"The requested package version could not be found.",'
            '"evidence":["ERROR: Could not find a version that satisfies the requirement fastapi==9.9.9"],'
            '"suggested_fix":["Check that the requested version is published."],'
            '"confidence":"high"}'
        )
        fake = FakeClient([response], model="test-model")
        with patch.dict(os.environ, {"ANTHROPIC_API_KEY": "test-key"}):
            with patch("ci_explainer.web_backend.AnthropicClient", return_value=fake) as client:
                result = explain_log(
                    raw_log,
                    use_model=True,
                    model="test-model",
                    api_key="sidebar-key",
                    max_tokens=1024,
                )

        client.assert_called_once_with(
            "test-model", api_key="sidebar-key", max_tokens=1024
        )
        self.assertEqual(result.source, "llm")
        self.assertEqual(result.evidence, [raw_log])

    def test_model_token_limit_is_validated(self):
        with patch.dict(os.environ, {"ANTHROPIC_API_KEY": "test-key"}):
            with self.assertRaisesRegex(ValueError, "between 1 and 8192"):
                explain_log("A failing log", use_model=True, max_tokens=0)


if __name__ == "__main__":
    unittest.main()
