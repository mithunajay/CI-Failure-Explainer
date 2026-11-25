import io
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

from ci_explainer.cli import main

ROOT = Path(__file__).parent.parent


class CliTests(unittest.TestCase):
    def test_explain_rules_only(self):
        buf = io.StringIO()
        with redirect_stdout(buf):
            code = main(["explain", str(ROOT / "data/sample/01_pip_no_dist.log"), "--rules-only"])
        self.assertEqual(code, 0)
        self.assertIn("dependency_install", buf.getvalue())

    def test_eval_rules_only_writes_results(self):
        with tempfile.TemporaryDirectory() as d:
            buf = io.StringIO()
            with redirect_stdout(buf):
                code = main(["eval", "--dataset", str(ROOT / "data/labeled.sample.jsonl"),
                             "--rules-only", "--out-dir", d])
            self.assertEqual(code, 0)
            self.assertTrue((Path(d) / "results_rules.jsonl").exists())
            self.assertIn("Category accuracy", buf.getvalue())

    def test_queue_flag(self):
        with tempfile.TemporaryDirectory() as d:
            q = Path(d) / "q.jsonl"
            with redirect_stdout(io.StringIO()):
                main(["explain", str(ROOT / "data/sample/04_oom.log"), "--rules-only", "--queue", str(q)])
            self.assertTrue(q.read_text().strip())


if __name__ == "__main__":
    unittest.main()
