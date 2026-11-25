# CI Failure Explainer

[![tests](https://github.com/mithunajay/ci-failure-explainer/actions/workflows/ci.yml/badge.svg)](https://github.com/mithunajay/ci-failure-explainer/actions/workflows/ci.yml)

Reads the log of a failed CI job and explains, in plain language, **why it failed** and **how to fix it**.
Built to be trusted: logs are treated as untrusted input, every claim must quote the log, and a human approves
results before anything is used.

> **Status:** working tool with 41 passing tests on fixtures. Accuracy on real logs has **not** been measured yet.
> See [Results](#results) to fill in your own numbers after you run the evaluation.

## Why this exists

When a pipeline goes red, engineers scroll through thousands of lines to find the one that matters.
Root-cause analysis on a failing system is a skill I use daily in field service (Cognex machine vision, PLCs).
This project applies the same method to software: find the failing step, quote the evidence, suggest a safe fix,
and say "I don't know" when the cause is unclear.

## How it works

```
raw log ──► clean ──► rules (baseline) ──┐
            │ strip ANSI/timestamps       │
            │ redact secrets              ▼
            │ keep tail + error context   LLM (wrapped as untrusted data)
            │                             │
            └──────────────────────────►  guardrails on the reply
                                          │  strict JSON schema
                                          │  evidence quotes must exist in the log
                                          │  no invented URLs, no secrets
                                          │  block dangerous fixes (sudo, curl | sh, --force...)
                                          ▼
                              valid? ── yes ─► explanation (source: llm)
                                 └──── no ──► rule-based fallback (source: fallback)
                                                       │
                                                       ▼
                                        human review: approve / edit / reject
```

| Component | File | What it does |
|---|---|---|
| Log cleaner | `log_cleaner.py` | Strips noise, redacts secrets, keeps the failure region |
| Rules | `rules.py` | 11 deterministic failure categories; baseline and fallback |
| Guardrails | `guardrails.py` | Injection detection, untrusted-data wrapping, output validation |
| LLM client | `llm.py` | Anthropic client behind a small interface; fake client for tests |
| Pipeline | `explainer.py` | Ties it together |
| Review queue | `review.py` | Human approval, edits, rejection, approval-rate stats |
| Sources | `github_source.py`, `gitlab_source.py` | Download failed job logs |
| Evaluation | `evaluation.py` | Accuracy, fix match, fallback rate, latency, cost; model comparison |

## Quick start

```bash
git clone https://github.com/mithunajay/ci-failure-explainer.git
cd ci-failure-explainer
python -m venv .venv && source .venv/bin/activate      # Windows: .venv\Scripts\activate
pip install -e ".[dev,anthropic]"
cp .env.example .env                                    # then fill in keys; export them (see below)
pytest -q                                               # 41 tests, no API key needed
```

Try it with no API key (rules only):

```bash
ci-explainer explain data/sample/01_pip_no_dist.log --rules-only
```

With a model:

```bash
export ANTHROPIC_API_KEY=...            # Windows PowerShell: $env:ANTHROPIC_API_KEY="..."
ci-explainer explain data/sample/06_injection.log --queue data/queue.jsonl
ci-explainer review                      # approve / edit / reject
```

`data/sample/06_injection.log` contains a line that tries to hijack an AI assistant. The tool flags it,
keeps the log inside untrusted delimiters, and rejects any reply that leaks secrets or quotes lines not in the log.

## Commands

| Command | Purpose |
|---|---|
| `ci-explainer explain LOG [--rules-only] [--model M] [--json] [--queue FILE]` | Explain one log (`-` reads stdin) |
| `ci-explainer fetch-github --repo owner/name --limit 50 --out data/raw` | Download failed Actions logs (needs `GITHUB_TOKEN`) |
| `ci-explainer fetch-gitlab --project ID --limit 50 --out data/raw` | Download failed GitLab job logs (needs `GITLAB_TOKEN`) |
| `ci-explainer eval --dataset FILE --models a,b` | Evaluate and compare models |
| `ci-explainer summarize --results FILE` | Recompute metrics after you grade fixes by hand |
| `ci-explainer review` | Human review of queued explanations |

## Evaluating on real data (this is what makes it credible)

1. `ci-explainer fetch-github --repo <public repo with many failures> --limit 100 --out data/raw`
2. Open `data/raw/labeled.todo.jsonl` and label **60 to 100** logs by hand. Follow [docs/LABELING_GUIDE.md](docs/LABELING_GUIDE.md).
3. `ci-explainer eval --dataset data/raw/labeled.todo.jsonl --rules-only` (baseline)
4. `ci-explainer eval --dataset data/raw/labeled.todo.jsonl --models <small-model>,<large-model>`
5. In each `results_*.jsonl`, set `human_fix_ok` to `true` or `false` by comparing the suggested fix with what actually fixed the build, then run `ci-explainer summarize --results ...`.

Details and metric definitions: [docs/EVALUATION.md](docs/EVALUATION.md).

## Results

Fill this table with your measured numbers. Do not publish numbers you have not measured.

| Approach | Logs | Category accuracy | Human-graded fix match | Fallback rate | Cost / 100 logs | Avg latency |
|---|---|---|---|---|---|---|
| Rules only | _N_ | _x%_ | _x%_ | n/a | $0 | <1 ms |
| Small model | _N_ | _x%_ | _x%_ | _x%_ | _$_ | _s_ |
| Large model | _N_ | _x%_ | _x%_ | _x%_ | _$_ | _s_ |

The 7 files in `data/sample/` are illustrative fixtures for tests, not a benchmark.

## Safety design

See [docs/SECURITY.md](docs/SECURITY.md). Summary: logs are untrusted; secrets are redacted before any model call;
the model's reply is validated; nothing is posted automatically; credentials are read from environment variables only.

## When AI is the wrong tool

Exact patterns (an OOM kill, a missing package, invalid YAML) are solved by the rule layer in microseconds for free.
The model earns its cost on logs where the cause is buried, multi-step, or phrased in a way no rule anticipates.
The evaluation shows where each one wins.

## Limitations

- English logs and common tooling (pip, npm, pytest, eslint, Docker, GitHub Actions, GitLab CI) only.
- The cleaner keeps about 160 lines; a cause far from any error keyword can be dropped.
- Rules are ordered heuristics and can misclassify wrapped errors.
- Redaction is pattern-based and can miss unusual secret formats. Do not feed it private logs without review.
- Model names and prices change; set them through environment variables.

## Project layout

```
src/ci_explainer/   package code
tests/              unit tests (run with pytest)
data/sample/        illustrative fixture logs
docs/               architecture, labeling, evaluation, security, GitHub launch
examples/           GitLab CI and GitHub Actions snippets
.github/workflows/  CI for this repo
```

## License

MIT. See [LICENSE](LICENSE).
