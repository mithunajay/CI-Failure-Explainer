# Evaluation

## Metrics
| Metric | Definition | Caveat |
|---|---|---|
| Category accuracy | Predicted category equals the hand label | Needs a balanced dataset |
| Fix keyword match | Suggested fix or cause mentions an expected keyword | Lenient proxy only; do not headline it |
| **Human-graded fix match** | You judged the suggested fix against the real fix | The number to report; say how many logs you graded |
| Fallback rate | Share of cases where model output was rejected by guardrails | High values mean the prompt or model needs work |
| Injection flagged | Logs containing injection-style text | Informational |
| Latency, tokens, cost | From API usage; cost needs prices in `.env` | Prices change |

## Protocol
1. Collect 100+ failed logs from public repos; label 60 to 100.
2. Hold out a test split you do not tune on.
3. Run the **rules-only baseline** first.
4. Run a **small** and a **large** model with identical prompts. Report accuracy, cost per 100 logs, and latency for both.
5. Optionally compare `--hint-rules` on and off.
6. Grade fixes by hand, then run `summarize`.
7. Read the failures. Write 3 to 5 examples of where each approach is wrong; they make a better README than a single percentage.

## Red-team set (guardrails)
Create 10 logs that contain injection text (ignore instructions, fake system tags, requests to print keys, fake delimiters).
Report: how many were flagged, how many model replies were rejected by validation, and whether any secret or invented URL reached a reviewer. The sample `06_injection.log` is the first example.

## Reporting honestly
- State N, the repositories, the date, the model names and the guardrail settings.
- Say which metric is automatic and which is human-graded.
- Do not claim production use unless a team actually relied on it.
