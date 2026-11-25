"""Turn a raw CI log into a short, safe excerpt.

Steps: strip ANSI codes and timestamps, drop CI markers, collapse repeated
lines, redact secrets, then keep the part of the log most likely to hold the
failure (the tail plus context around error-looking lines).
"""
from __future__ import annotations

import re
from dataclasses import dataclass

ANSI_RE = re.compile(r"\x1b\[[0-9;?]*[ -/]*[@-~]")
TS_RE = re.compile(r"^\s*\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}(?:\.\d+)?Z?\s*")
GL_SECTION_RE = re.compile(r"section_(?:start|end):\d+:[\w.\-]+\r?")
GH_MARKER_RE = re.compile(r"^##\[(?:debug|group|endgroup)\]")

# (pattern, replacement). The last pattern keeps the key name.
SECRET_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"gh[pousr]_[A-Za-z0-9]{36,}"), "[REDACTED]"),
    (re.compile(r"github_pat_[A-Za-z0-9_]{20,}"), "[REDACTED]"),
    (re.compile(r"glpat-[A-Za-z0-9_\-]{20,}"), "[REDACTED]"),
    (re.compile(r"AKIA[0-9A-Z]{16}"), "[REDACTED]"),
    (re.compile(r"sk-[A-Za-z0-9_\-]{20,}"), "[REDACTED]"),
    (re.compile(r"(?i)bearer\s+[A-Za-z0-9._\-]{20,}"), "[REDACTED]"),
    (re.compile(r"(?i)\b(password|passwd|secret|token|api[_-]?key)\s*[=:]\s*\S+"),
     r"\1=[REDACTED]"),
]

ERROR_RE = re.compile(
    r"(?i)\b(error|errors|failed|failure|fatal|exception|traceback|panic|denied|"
    r"not found|cannot|can't|unable|timed? ?out|exit code|exited with|killed|oom)\b"
)


@dataclass
class CleanedLog:
    text: str
    original_lines: int
    kept_lines: int
    redactions: int


def redact(text: str) -> tuple[str, int]:
    """Replace likely secrets. Returns (clean_text, number_of_redactions)."""
    total = 0
    for pattern, repl in SECRET_PATTERNS:
        text, n = pattern.subn(repl, text)
        total += n
    return text, total


def normalize(s: str) -> str:
    """Collapse whitespace so evidence quotes can be compared reliably."""
    return " ".join(s.split())


def _basic_lines(raw: str) -> list[str]:
    lines: list[str] = []
    for line in raw.splitlines():
        line = GL_SECTION_RE.sub("", line)
        line = ANSI_RE.sub("", line).replace("\r", "")
        line = TS_RE.sub("", line)
        line = GH_MARKER_RE.sub("", line).rstrip()
        if line.strip():
            lines.append(line)
    # collapse consecutive duplicates
    out: list[str] = []
    i = 0
    while i < len(lines):
        j = i
        while j + 1 < len(lines) and lines[j + 1] == lines[i]:
            j += 1
        out.append(lines[i])
        if j > i:
            out.append(f"(previous line repeated {j - i} more times)")
        i = j + 1
    return out


def clean_log(
    raw: str, max_lines: int = 160, context: int = 6, max_chars: int = 12000
) -> CleanedLog:
    lines = _basic_lines(raw)
    original = len(lines)
    text, redactions = redact("\n".join(lines))
    lines = text.split("\n") if text else []

    if len(lines) > max_lines:
        keep: set[int] = set(range(max(0, len(lines) - 25), len(lines)))
        hits = [i for i, l in enumerate(lines) if ERROR_RE.search(l)]
        for i in hits[-60:]:
            keep.update(range(max(0, i - context), min(len(lines), i + context + 1)))
        idx = sorted(keep)[-max_lines:]
        selected: list[str] = []
        prev = None
        for i in idx:
            if prev is not None and i != prev + 1:
                selected.append(f"[... {i - prev - 1} lines omitted ...]")
            selected.append(lines[i])
            prev = i
        lines = selected

    out = "\n".join(lines)
    if len(out) > max_chars:
        out = "[... earlier output truncated ...]\n" + out[-max_chars:]
    return CleanedLog(text=out, original_lines=original,
                      kept_lines=len(out.splitlines()), redactions=redactions)
