"""Human review queue. Nothing is ever posted automatically: a person approves,
edits, or rejects each explanation, and every decision is logged."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable


def append_to_queue(queue_path: str | Path, item_id: str, explanation: dict) -> None:
    path = Path(queue_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps({"id": item_id, **explanation}) + "\n")


def _read_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    return [json.loads(l) for l in path.read_text(encoding="utf-8").splitlines() if l.strip()]


def review_queue(queue_path: str | Path, decisions_path: str | Path,
                 input_fn: Callable[[str], str] = input,
                 print_fn: Callable[[str], None] = print) -> int:
    """Interactive review. Returns the number of decisions made this session."""
    queue = _read_jsonl(Path(queue_path))
    dpath = Path(decisions_path)
    done = {d["id"] for d in _read_jsonl(dpath)}
    made = 0
    dpath.parent.mkdir(parents=True, exist_ok=True)

    for item in queue:
        if item["id"] in done:
            continue
        print_fn(f"\n=== {item['id']} ({item['source']}, confidence: {item['confidence']}) ===")
        print_fn(f"Category : {item['category']}")
        print_fn(f"Summary  : {item['summary']}")
        print_fn(f"Cause    : {item['root_cause']}")
        for e in item["evidence"]:
            print_fn(f"Evidence : {e}")
        for i, fix in enumerate(item["suggested_fix"], 1):
            print_fn(f"Fix {i}    : {fix}")
        if item.get("injection_flags"):
            print_fn(f"WARNING  : injection-style text in log: {item['injection_flags']}")

        while True:
            choice = input_fn("[a]pprove  [e]dit  [r]eject  [s]kip  [q]uit > ").strip().lower()
            if choice in {"a", "e", "r", "s", "q"}:
                break
        if choice == "q":
            break
        if choice == "s":
            continue
        record = {"id": item["id"], "decision": {"a": "approved", "e": "edited", "r": "rejected"}[choice],
                  "edited_summary": None,
                  "at": datetime.now(timezone.utc).isoformat()}
        if choice == "e":
            record["edited_summary"] = input_fn("New summary > ").strip()
        with dpath.open("a", encoding="utf-8") as f:
            f.write(json.dumps(record) + "\n")
        made += 1
    return made


def approval_rate(decisions_path: str | Path) -> dict:
    decisions = _read_jsonl(Path(decisions_path))
    n = len(decisions)
    counts = {k: sum(1 for d in decisions if d["decision"] == k)
              for k in ("approved", "edited", "rejected")}
    return {"reviewed": n, **counts,
            "approval_rate": (counts["approved"] / n) if n else None}
