# Architecture

## Goals
1. Explain a CI failure in plain language with evidence from the log.
2. Never trust the log or the model blindly.
3. Make quality measurable.

## Data flow
1. **Clean** (`log_cleaner.py`): remove ANSI codes, timestamps, CI markers, repeated lines; redact secrets; keep the tail and the context around error-like lines (about 160 lines, 12,000 characters).
2. **Classify by rules** (`rules.py`): ordered regex rules, most specific first. Used as a baseline, a fallback, and an optional hint to the model (`--hint-rules`).
3. **Detect injection** (`guardrails.detect_injection`): flags phrases like "ignore all previous instructions". Flags are recorded and shown to the reviewer; they do not stop the run because the log is still wrapped as data.
4. **Call the model** (`llm.py`): temperature 0, system prompt says the log is untrusted data, reply must be one JSON object.
5. **Validate** (`guardrails.validate_output`): schema, allowed categories, length limits, evidence lines found verbatim in the cleaned log, URLs must appear in the log, no secret-like strings, no dangerous fix commands.
6. **Fallback**: invalid reply, timeout, or API error returns the rule-based answer with `source = "fallback"` and the error list.
7. **Human review** (`review.py`): approve, edit, or reject; decisions logged to JSONL.

## Why these choices
- **Evidence must exist in the log.** This turns "the model sounds confident" into something checkable.
- **Rules first as a baseline.** It shows whether the model adds value over free regexes.
- **No automatic posting.** The cost of a wrong confident answer in a team chat is higher than the cost of one review click.
- **Standard library only for the core.** Easy to audit; the Anthropic SDK is an optional extra and the model sits behind a small interface (`LLMClient`), so another provider is one class.
- **Prices from environment variables.** Prices change; copy them from your provider's pricing page.

## Extending
- Add a rule: append to `RULES` in `rules.py` (order matters) and add a fixture plus a test.
- Add a provider: implement `complete(system, user) -> LLMResponse` and set `model`.
- Add a category: add it to `CATEGORIES` in `rules.py`; the prompt and validator pick it up automatically.
