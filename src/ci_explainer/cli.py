"""Command line interface: ci-explainer <command>."""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from . import evaluation as ev
from .explainer import explain
from .llm import AnthropicClient, price_from_env
from .review import append_to_queue, approval_rate, review_queue

DEFAULT_MODEL = os.environ.get("CI_EXPLAINER_MODEL", "claude-haiku-5-5")


def _client(model: str | None, rules_only: bool):
    return None if rules_only else AnthropicClient(model or DEFAULT_MODEL)


def _print_explanation(exp) -> None:
    print(f"Category   : {exp.category}  (source: {exp.source}, confidence: {exp.confidence})")
    print(f"Summary    : {exp.summary}")
    print(f"Likely cause: {exp.root_cause}")
    for e in exp.evidence:
        print(f"Evidence   : {e}")
    for i, f in enumerate(exp.suggested_fix, 1):
        print(f"Fix {i}      : {f}")
    if exp.injection_flags:
        print(f"WARNING    : injection-style text found in log: {exp.injection_flags}")
    if exp.errors:
        print(f"Guardrail  : model output rejected -> {exp.errors}")
    if exp.redactions:
        print(f"Redacted   : {exp.redactions} possible secret(s) removed before analysis")


def cmd_explain(a) -> int:
    raw = sys.stdin.read() if a.log == "-" else Path(a.log).read_text(encoding="utf-8", errors="replace")
    exp = explain(raw, _client(a.model, a.rules_only), hint_rules=a.hint_rules)
    if a.json:
        print(json.dumps(exp.to_dict(), indent=2))
    else:
        _print_explanation(exp)
    if a.queue:
        append_to_queue(a.queue, Path(a.log).stem if a.log != "-" else "stdin", exp.to_dict())
        print(f"Queued for human review: {a.queue}")
    return 0


def cmd_fetch_github(a) -> int:
    from .github_source import fetch_failed_logs
    token = os.environ.get("GITHUB_TOKEN")
    if not token:
        print("Set GITHUB_TOKEN (see .env.example)"); return 2
    m = fetch_failed_logs(a.repo, token, a.limit, a.out)
    print(f"Saved logs to {a.out}. Label them in {m}, then run `eval`.")
    return 0


def cmd_fetch_gitlab(a) -> int:
    from .gitlab_source import fetch_failed_logs
    token = os.environ.get("GITLAB_TOKEN")
    if not token:
        print("Set GITLAB_TOKEN (see .env.example)"); return 2
    m = fetch_failed_logs(a.project, token, a.limit, a.out, a.base_url)
    print(f"Saved logs to {a.out}. Label them in {m}, then run `eval`.")
    return 0


def cmd_eval(a) -> int:
    cases = ev.load_dataset(a.dataset)
    if not cases:
        print("No labeled cases found. Fill in true_category in the dataset."); return 2
    models = [None] if a.rules_only else [m.strip() for m in a.models.split(",")]
    p_in, p_out = price_from_env()
    for model in models:
        label = "rules-only baseline" if model is None else model
        rows = ev.run_eval(cases, _client(model, a.rules_only), hint_rules=a.hint_rules)
        out = Path(a.out_dir) / f"results_{(model or 'rules').replace('/', '_')}.jsonl"
        ev.save_results(rows, out)
        print(ev.format_report(ev.summarize(rows, p_in, p_out), label))
        print(f"(per-case results saved to {out}; set human_fix_ok then run `summarize`)\n")
    return 0


def cmd_summarize(a) -> int:
    p_in, p_out = price_from_env()
    rows = ev.load_results(a.results)
    print(ev.format_report(ev.summarize(rows, p_in, p_out), a.results))
    return 0


def cmd_review(a) -> int:
    n = review_queue(a.queue, a.decisions)
    print(f"{n} decision(s) recorded. Stats: {approval_rate(a.decisions)}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="ci-explainer", description="Explain failed CI logs.")
    sub = p.add_subparsers(dest="cmd", required=True)

    e = sub.add_parser("explain", help="Explain one log file (use - for stdin)")
    e.add_argument("log")
    e.add_argument("--model", default=None)
    e.add_argument("--rules-only", action="store_true", help="No LLM, rules only")
    e.add_argument("--hint-rules", action="store_true", help="Give the model the rule guess")
    e.add_argument("--json", action="store_true")
    e.add_argument("--queue", default=None, help="Append result to a review queue file")
    e.set_defaults(fn=cmd_explain)

    g = sub.add_parser("fetch-github", help="Download failed GitHub Actions logs")
    g.add_argument("--repo", required=True, help="owner/name")
    g.add_argument("--limit", type=int, default=25)
    g.add_argument("--out", default="data/raw")
    g.set_defaults(fn=cmd_fetch_github)

    l = sub.add_parser("fetch-gitlab", help="Download failed GitLab CI job logs")
    l.add_argument("--project", required=True, help="numeric ID or URL-encoded path")
    l.add_argument("--base-url", default="https://gitlab.com")
    l.add_argument("--limit", type=int, default=25)
    l.add_argument("--out", default="data/raw")
    l.set_defaults(fn=cmd_fetch_gitlab)

    v = sub.add_parser("eval", help="Evaluate on a labeled dataset")
    v.add_argument("--dataset", required=True)
    v.add_argument("--models", default=DEFAULT_MODEL, help="Comma-separated model names to compare")
    v.add_argument("--rules-only", action="store_true")
    v.add_argument("--hint-rules", action="store_true")
    v.add_argument("--out-dir", default="data/results")
    v.set_defaults(fn=cmd_eval)

    s = sub.add_parser("summarize", help="Recompute metrics from a results file after human grading")
    s.add_argument("--results", required=True)
    s.set_defaults(fn=cmd_summarize)

    r = sub.add_parser("review", help="Approve, edit, or reject queued explanations")
    r.add_argument("--queue", default="data/queue.jsonl")
    r.add_argument("--decisions", default="data/reviews.jsonl")
    r.set_defaults(fn=cmd_review)
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return args.fn(args)
    except RuntimeError as e:
        print(f"Error: {e}")
        return 2


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
