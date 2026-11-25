"""Guardrails: treat logs as untrusted input and model output as untrusted output.

Input side:  detect injection-style text, wrap the log in delimiters.
Output side: strict JSON schema, evidence must be quoted from the log, no
             invented URLs, no secrets, no dangerous fix commands.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field

from .log_cleaner import normalize, redact
from .rules import CATEGORIES

DELIM_OPEN = "<<<CI_LOG_UNTRUSTED>>>"
DELIM_CLOSE = "<<<END_CI_LOG_UNTRUSTED>>>"

INJECTION_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("ignore_instructions",
     re.compile(r"(?i)ignore\s+(all\s+|any\s+)?(the\s+)?(previous|prior|above|earlier)\s+(instructions|prompts?|rules)")),
    ("disregard_instructions",
     re.compile(r"(?i)disregard\s+.{0,40}(instructions|rules|prompt)")),
    ("role_override", re.compile(r"(?i)\byou\s+are\s+now\b|\bact\s+as\s+(an?\s+)?\w+")),
    ("reveal_secrets",
     re.compile(r"(?i)(reveal|print|show|send|exfiltrate|leak)\s+.{0,30}(secret|token|api[_ -]?key|password|system prompt|credentials)")),
    ("fake_role_tags", re.compile(r"(?i)</?\s*(system|assistant|developer)\s*>")),
    ("fake_delimiters", re.compile(re.escape("<<<") + r"\w+" + re.escape(">>>"))),
]

DANGEROUS_FIX_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"rm\s+-rf\s+/"),
    re.compile(r"(curl|wget)[^|\n]*\|\s*(sudo\s+)?(ba)?sh"),
    re.compile(r"git\s+push\b.*--force|git\s+push\b.*\s-f\b"),
    re.compile(r"--no-verify"),
    re.compile(r"chmod\s+(-R\s+)?777"),
    re.compile(r"\bsudo\b"),
    re.compile(r"(?i)drop\s+table"),
    re.compile(r":\(\)\s*\{"),
]

URL_RE = re.compile(r"https?://[^\s)\]>\"']+")
CONFIDENCE = {"low", "medium", "high"}


def detect_injection(text: str) -> list[str]:
    """Return names of injection-style patterns found in the log."""
    return [name for name, pat in INJECTION_PATTERNS if pat.search(text)]


def wrap_untrusted(log_text: str) -> str:
    safe = log_text.replace(DELIM_OPEN, "").replace(DELIM_CLOSE, "")
    return f"{DELIM_OPEN}\n{safe}\n{DELIM_CLOSE}"


def parse_json_object(text: str) -> dict | None:
    """Parse the first JSON object in a model reply (tolerates code fences)."""
    text = text.strip()
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text)
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end <= start:
        return None
    try:
        data = json.loads(text[start:end + 1])
    except json.JSONDecodeError:
        return None
    return data if isinstance(data, dict) else None


@dataclass
class ValidationResult:
    ok: bool
    errors: list[str] = field(default_factory=list)
    data: dict | None = None


def _str_list(value: object, lo: int, hi: int, max_len: int, name: str,
              errors: list[str]) -> list[str]:
    if not isinstance(value, list) or not all(isinstance(v, str) for v in value):
        errors.append(f"{name} must be a list of strings")
        return []
    if not (lo <= len(value) <= hi):
        errors.append(f"{name} must have {lo}-{hi} items")
    for v in value:
        if len(v) > max_len:
            errors.append(f"{name} item longer than {max_len} chars")
    return value


def validate_output(data: dict, log_text: str) -> ValidationResult:
    errors: list[str] = []
    for key in ("category", "summary", "root_cause", "evidence", "suggested_fix", "confidence"):
        if key not in data:
            errors.append(f"missing key: {key}")
    if errors:
        return ValidationResult(False, errors)

    category = data["category"]
    if category not in CATEGORIES:
        errors.append(f"category not allowed: {category!r}")
    if data["confidence"] not in CONFIDENCE:
        errors.append("confidence must be low, medium, or high")
    for key, limit in (("summary", 400), ("root_cause", 700)):
        if not isinstance(data[key], str) or not data[key].strip():
            errors.append(f"{key} must be a non-empty string")
        elif len(data[key]) > limit:
            errors.append(f"{key} longer than {limit} chars")

    evidence_min = 0 if category == "unknown" else 1
    evidence = _str_list(data["evidence"], evidence_min, 3, 400, "evidence", errors)
    fixes = _str_list(data["suggested_fix"], 1, 5, 400, "suggested_fix", errors)

    norm_log = normalize(log_text)
    for quote in evidence:
        if normalize(quote) not in norm_log:
            errors.append(f"evidence not found in log: {quote[:60]!r}")

    texts = [str(data["summary"]), str(data["root_cause"]), *fixes]
    for t in texts:
        for url in URL_RE.findall(t):
            if url not in log_text:
                errors.append(f"URL not present in log: {url[:60]}")
        if redact(t)[1] > 0:
            errors.append("output contains something that looks like a secret")
    for fix in fixes:
        for pat in DANGEROUS_FIX_PATTERNS:
            if pat.search(fix):
                errors.append(f"dangerous suggestion blocked: {fix[:60]!r}")
                break

    return ValidationResult(not errors, errors, data if not errors else None)
