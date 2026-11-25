import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from ci_explainer import github_source as gh


class GithubSourceTests(unittest.TestCase):
    def test_fetch_writes_logs_and_labeling_template(self):
        runs = {"workflow_runs": [{"id": 11}]}
        jobs = {"jobs": [{"id": 22, "conclusion": "failure", "html_url": "u"},
                         {"id": 23, "conclusion": "success"}]}

        def fake_json(url, token):
            return runs if "/runs?" in url else jobs

        with tempfile.TemporaryDirectory() as d, \
                mock.patch.object(gh, "get_json", side_effect=fake_json), \
                mock.patch.object(gh, "get_log_text", return_value="ERROR: boom"):
            manifest = gh.fetch_failed_logs("o/r", "tok", 5, d, pause_s=0)
            files = sorted(p.name for p in Path(d).glob("*.log"))
            self.assertEqual(files, ["o_r_11_22.log"])
            row = json.loads(manifest.read_text().splitlines()[0])
            self.assertEqual(row["true_category"], "")
            self.assertEqual(row["log_path"], "o_r_11_22.log")

    def test_token_not_sent_to_redirect_host(self):
        sent = {}

        def fake_open(url, token):
            return b"", "https://signed.example/log"

        class R:
            def __enter__(self): return self
            def __exit__(self, *a): pass
            def read(self): return b"log text"

        def fake_urlopen(req, timeout=0):
            sent["headers"] = dict(req.header_items())
            return R()

        with mock.patch.object(gh, "_open", side_effect=fake_open), \
                mock.patch("urllib.request.urlopen", side_effect=fake_urlopen):
            self.assertEqual(gh.get_log_text("https://api.github.com/x", "secret"), "log text")
        self.assertNotIn("Authorization", sent["headers"])


if __name__ == "__main__":
    unittest.main()
