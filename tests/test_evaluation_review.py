import json
import tempfile
import unittest
from pathlib import Path

from ci_explainer import evaluation as ev
from ci_explainer.review import append_to_queue, approval_rate, review_queue

DATASET = Path(__file__).parent.parent / "data" / "labeled.sample.jsonl"


class EvalTests(unittest.TestCase):
    def test_rules_baseline_on_fixtures(self):
        cases = ev.load_dataset(DATASET)
        self.assertEqual(len(cases), 7)
        rows = ev.run_eval(cases, None)
        s = ev.summarize(rows)
        self.assertEqual(s["category_accuracy"], 1.0)
        self.assertEqual(s["injection_flagged"], 1)
        self.assertEqual(s["fallback_rate"], 0.0)

    def test_human_grading_summary(self):
        rows = [
            {"category_ok": True, "fix_keyword_ok": True, "human_fix_ok": True, "fallback": False,
             "injection_flagged": False, "latency_s": 1.0, "input_tokens": 1000, "output_tokens": 100},
            {"category_ok": False, "fix_keyword_ok": False, "human_fix_ok": False, "fallback": True,
             "injection_flagged": True, "latency_s": 3.0, "input_tokens": 3000, "output_tokens": 300},
            {"category_ok": True, "fix_keyword_ok": None, "human_fix_ok": None, "fallback": False,
             "injection_flagged": False, "latency_s": 2.0, "input_tokens": 2000, "output_tokens": 200},
        ]
        s = ev.summarize(rows, price_in=1.0, price_out=5.0)
        self.assertAlmostEqual(s["category_accuracy"], 2 / 3)
        self.assertEqual(s["human_fix_rate"], 0.5)
        self.assertEqual(s["human_graded"], 2)
        self.assertAlmostEqual(s["fallback_rate"], 1 / 3)
        # (6000*1 + 600*5) / 1e6 = 0.009 total for 3 cases -> 0.3 per 100
        self.assertAlmostEqual(s["cost_usd_per_100_cases"], 0.3)

    def test_unlabeled_rows_skipped(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "x.jsonl"
            p.write_text(json.dumps({"id": "a", "log_path": "a.log", "true_category": ""}) + "\n")
            self.assertEqual(ev.load_dataset(p), [])

    def test_report_formats(self):
        s = ev.summarize(ev.run_eval(ev.load_dataset(DATASET), None))
        text = ev.format_report(s, "rules")
        self.assertIn("Category accuracy: 100.0%", text)


class ReviewTests(unittest.TestCase):
    def test_review_flow_and_stats(self):
        with tempfile.TemporaryDirectory() as d:
            q, dec = Path(d) / "q.jsonl", Path(d) / "d.jsonl"
            base = {"category": "network", "summary": "s", "root_cause": "c", "evidence": ["e"],
                    "suggested_fix": ["f"], "confidence": "medium", "source": "llm",
                    "injection_flags": []}
            for i in ("a", "b", "c"):
                append_to_queue(q, i, base)
            answers = iter(["a", "e", "Better summary", "r"])
            n = review_queue(q, dec, input_fn=lambda _: next(answers), print_fn=lambda _: None)
            self.assertEqual(n, 3)
            stats = approval_rate(dec)
            self.assertEqual((stats["approved"], stats["edited"], stats["rejected"]), (1, 1, 1))
            # Re-running skips already-decided items
            n2 = review_queue(q, dec, input_fn=lambda _: "q", print_fn=lambda _: None)
            self.assertEqual(n2, 0)


if __name__ == "__main__":
    unittest.main()
