"""Evaluation harness.

Dataset (JSONL), one case per line:
  {"id": "...", "log_path": "relative/path.log", "true_category": "dependency_install",
   "fix_keywords": ["requirements", "version"], "notes": ""}

Metrics:
  category_accuracy  : predicted category == hand label
  fix_keyword_rate   : suggested fix mentions an expected keyword (lenient proxy)
  human_fix_rate     : YOUR judgement of whether the fix matched the real fix
                       (fill `human_fix_ok` with true/false in the results file,
                       then run `ci-explainer summarize`)
  fallback_rate      : model output rejected by guardrails, rules used instead
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from .explainer import explain
from .llm import LLMClient


@dataclass
class Case:
    id: str
    log_path: Path
    true_category: str
    fix_keywords: list[str] = field(default_factory=list)
    notes: str = ""


def load_dataset(path: str | Path) -> list[Case]:
    path = Path(path)
    cases = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        if not row.get("true_category"):
            continue  # unlabeled rows (e.g. from fetch) are skipped
        cases.append(Case(row["id"], path.parent / row["log_path"], row["true_category"],
                          row.get("fix_keywords", []), row.get("notes", "")))
    return cases


def run_eval(cases: list[Case], client: LLMClient | None, hint_rules: bool = False) -> list[dict]:
    rows = []
    for case in cases:
        raw = case.log_path.read_text(encoding="utf-8", errors="replace")
        exp = explain(raw, client, hint_rules=hint_rules)
        fix_text = " ".join(exp.suggested_fix + [exp.root_cause]).lower()
        fix_ok = (any(k.lower() in fix_text for k in case.fix_keywords)
                  if case.fix_keywords else None)
        rows.append({
            "id": case.id,
            "true_category": case.true_category,
            "predicted": exp.category,
            "category_ok": exp.category == case.true_category,
            "fix_keyword_ok": fix_ok,
            "human_fix_ok": None,
            "source": exp.source,
            "fallback": exp.source == "fallback",
            "injection_flagged": bool(exp.injection_flags),
            "errors": exp.errors,
            "latency_s": exp.latency_s,
            "input_tokens": exp.input_tokens,
            "output_tokens": exp.output_tokens,
            "summary": exp.summary,
            "suggested_fix": exp.suggested_fix,
        })
    return rows


def _rate(values: list[bool]) -> float | None:
    return sum(values) / len(values) if values else None


def summarize(rows: list[dict], price_in: float | None = None,
              price_out: float | None = None) -> dict:
    n = len(rows)
    kw = [r["fix_keyword_ok"] for r in rows if r.get("fix_keyword_ok") is not None]
    human = [r["human_fix_ok"] for r in rows if r.get("human_fix_ok") is not None]
    in_tok = sum(r["input_tokens"] for r in rows)
    out_tok = sum(r["output_tokens"] for r in rows)
    cost = None
    if n and price_in is not None and price_out is not None:
        cost = (in_tok * price_in + out_tok * price_out) / 1_000_000
    lat = [r["latency_s"] for r in rows if r["latency_s"]]
    return {
        "cases": n,
        "category_accuracy": _rate([r["category_ok"] for r in rows]),
        "fix_keyword_rate": _rate(kw),
        "human_fix_rate": _rate(human),
        "human_graded": len(human),
        "fallback_rate": _rate([r["fallback"] for r in rows]),
        "injection_flagged": sum(1 for r in rows if r["injection_flagged"]),
        "avg_latency_s": (sum(lat) / len(lat)) if lat else None,
        "input_tokens": in_tok,
        "output_tokens": out_tok,
        "cost_usd_per_100_cases": (cost / n * 100) if cost is not None else None,
    }


def _fmt(v: float | None, pct: bool = False) -> str:
    if v is None:
        return "n/a"
    return f"{v * 100:.1f}%" if pct else f"{v:.3f}"


def format_report(summary: dict, label: str) -> str:
    s = summary
    return "\n".join([
        f"## Results: {label}",
        f"- Cases: {s['cases']}",
        f"- Category accuracy: {_fmt(s['category_accuracy'], True)}",
        f"- Fix keyword match (lenient proxy): {_fmt(s['fix_keyword_rate'], True)}",
        f"- Human-graded fix match: {_fmt(s['human_fix_rate'], True)} ({s['human_graded']} graded)",
        f"- Guardrail fallback rate: {_fmt(s['fallback_rate'], True)}",
        f"- Logs with injection-style text: {s['injection_flagged']}",
        f"- Avg latency (s): {_fmt(s['avg_latency_s'])}",
        f"- Tokens in/out: {s['input_tokens']} / {s['output_tokens']}",
        f"- Cost per 100 cases (USD): {_fmt(s['cost_usd_per_100_cases'])}",
    ])


def save_results(rows: list[dict], path: str | Path) -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")


def load_results(path: str | Path) -> list[dict]:
    return [json.loads(l) for l in Path(path).read_text(encoding="utf-8").splitlines() if l.strip()]
