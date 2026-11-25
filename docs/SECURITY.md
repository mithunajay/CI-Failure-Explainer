# Security and safety notes

## Threats and mitigations
| Threat | Mitigation |
|---|---|
| Prompt injection in log text (a malicious PR or dependency prints instructions) | Log wrapped in delimiters; system prompt says never follow instructions in it; delimiter look-alikes stripped; injection phrases flagged for the reviewer; output validated so obedience cannot leak data |
| Secrets in logs reach the model or the reviewer | Pattern-based redaction before any model call; output scanned for secret-like strings |
| Hallucinated causes or evidence | Evidence must appear verbatim in the cleaned log; otherwise rule-based fallback |
| Invented links (phishing risk) | URLs in output must already appear in the log |
| Harmful "fix" advice | Block list: `sudo`, `curl | sh`, `git push --force`, `--no-verify`, `chmod 777`, `rm -rf /`, SQL drops |
| Token theft via redirects | GitHub log download follows the redirect without sending the token to the second host (tested) |
| Over-trust in automation | Nothing is posted automatically; human review with logged decisions |
| Credential leaks in the repo | Keys only from environment variables; `.env` is git-ignored |

## Limits
- Redaction is pattern-based and will miss unusual secret formats.
- Injection detection is a flag, not a guarantee. The real protection is the combination of wrapping, validation, and review.
- Do not run on logs from untrusted forks inside a workflow that has secrets.
- Third-party model providers receive the cleaned excerpt. Do not use private logs without permission.

## Reporting a vulnerability
Open a private security advisory on the GitHub repository (Security tab), or email the maintainer.
