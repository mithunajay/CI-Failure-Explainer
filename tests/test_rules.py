import unittest
from pathlib import Path

from ci_explainer.log_cleaner import clean_log
from ci_explainer.rules import classify

SAMPLES = Path(__file__).parent.parent / "data" / "sample"

EXPECTED = {
    "01_pip_no_dist.log": "dependency_install",
    "02_pytest_fail.log": "test_failure",
    "03_eslint.log": "lint_format",
    "04_oom.log": "out_of_memory",
    "05_network.log": "network",
    "06_injection.log": "dependency_install",
    "07_workflow_yaml.log": "config_syntax",
}


class RuleTests(unittest.TestCase):
    def test_sample_logs(self):
        for name, category in EXPECTED.items():
            with self.subTest(name):
                text = clean_log((SAMPLES / name).read_text()).text
                match = classify(text)
                self.assertIsNotNone(match)
                self.assertEqual(match.category, category)

    def test_unknown_returns_none(self):
        self.assertIsNone(classify("everything is fine"))

    def test_evidence_comes_from_log(self):
        text = clean_log((SAMPLES / "01_pip_no_dist.log").read_text()).text
        self.assertIn(classify(text).evidence, text)


if __name__ == "__main__":
    unittest.main()
