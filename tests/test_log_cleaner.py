import unittest

from ci_explainer.log_cleaner import clean_log, normalize, redact


class CleanerTests(unittest.TestCase):
    def test_strips_ansi_and_timestamps(self):
        raw = "2026-03-01T10:00:01.000Z \x1b[31mERROR\x1b[0m: boom\n"
        out = clean_log(raw).text
        self.assertEqual(out, "ERROR: boom")

    def test_removes_github_markers_keeps_error_lines(self):
        raw = "##[group]Run tests\n##[error]Process completed with exit code 1.\n"
        out = clean_log(raw).text
        self.assertNotIn("##[group]", out)
        self.assertIn("##[error]Process completed", out)

    def test_collapses_repeated_lines(self):
        raw = "\n".join(["retrying..."] * 6 + ["done"])
        out = clean_log(raw).text
        self.assertEqual(out.count("retrying..."), 1)
        self.assertIn("repeated 5 more times", out)

    def test_redacts_secrets(self):
        token = "ghp_" + "a" * 36
        text, n = redact(f"token {token} and password=hunter2 and AKIA{'B' * 16}")
        self.assertNotIn(token, text)
        self.assertNotIn("hunter2", text)
        self.assertEqual(n, 3)

    def test_long_log_keeps_failure_and_tail(self):
        lines = [f"step {i} ok" for i in range(500)]
        lines[200] = "ERROR: the real problem here"
        lines += ["tail line"]
        res = clean_log("\n".join(lines), max_lines=60)
        self.assertIn("the real problem here", res.text)
        self.assertIn("tail line", res.text)
        self.assertIn("lines omitted", res.text)
        self.assertLessEqual(res.kept_lines, 70)

    def test_normalize(self):
        self.assertEqual(normalize("a   b\n c"), "a b c")


if __name__ == "__main__":
    unittest.main()
