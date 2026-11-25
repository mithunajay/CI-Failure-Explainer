# Launching this project on GitHub

Your GitHub username in your resume is `mithunajay`. Replace it if the repo goes elsewhere.

## 1. Check locally
```bash
python -m venv .venv && source .venv/bin/activate     # Windows: .venv\Scripts\activate
pip install -e ".[dev,anthropic]"
pytest -q                                             # expect 41 passed
ci-explainer explain data/sample/01_pip_no_dist.log --rules-only
```

## 2. Create the repository
**Option A, website:** github.com → New repository → name `ci-failure-explainer` → Public → do NOT add a README, .gitignore or license (they already exist) → Create.

**Option B, GitHub CLI:** `gh auth login`, then see step 3.

## 3. Push the code
```bash
cd ci-failure-explainer
git init -b main
git add .
git status                      # confirm .env is NOT listed
git commit -m "Initial commit: CI failure explainer with guardrails, review queue, and eval harness"

# Option A
git remote add origin https://github.com/mithunajay/ci-failure-explainer.git
git push -u origin main

# Option B (creates the repo and pushes)
gh repo create ci-failure-explainer --public --source=. --remote=origin --push
```

## 4. Confirm Actions runs
Open the **Actions** tab. The `tests` workflow should go green on Python 3.10, 3.11 and 3.12. If it fails, open the run, read the failing step, and fix it (a nice test of the tool itself).

## 5. Polish the repo page
- **About** (gear icon next to About): description "Explains failed CI logs with evidence, injection guardrails, and human review"; topics `ci`, `llm`, `devops`, `github-actions`, `gitlab-ci`, `ai-safety`, `python`.
- Pin the repo on your profile (Profile → Customize your pins).
- Keep the README `Status` honest until you have real results.

## 6. Add secrets only if you use the example workflow
Settings → Secrets and variables → Actions → New repository secret: `ANTHROPIC_API_KEY`. Never paste keys into code, issues, or logs.

## 7. Run the real evaluation, then update the README
Follow `docs/LABELING_GUIDE.md` and `docs/EVALUATION.md`. Replace the placeholders in the README **Results** table with measured numbers, commit, and push:
```bash
git add README.md
git commit -m "Add measured evaluation results"
git push
```

## 8. Optional: GitLab mirror
For GitLab-relevant credibility, also push to GitLab and run the example `.gitlab-ci.yml` job:
```bash
git remote add gitlab https://gitlab.com/<your-username>/ci-failure-explainer.git
git push gitlab main
```

## 9. Tag a release
```bash
git tag -a v0.1.0 -m "First release"
git push origin v0.1.0
```
Then GitHub → Releases → Draft a new release from the tag.

## 10. What to put on your resume
Only after step 7, using your real numbers:

> **CI Failure Explainer** (Python, LLM API, GitHub Actions, GitLab CI): explains failed CI logs with quoted evidence, prompt-injection guardrails, and a human review step. Accuracy [X]% on [N] hand-labeled public logs; [small model] vs [large model] cost per 100 logs [A] vs [B]. github.com/mithunajay/ci-failure-explainer

Before step 7, describe it as "built the tool and 41 tests; evaluation in progress". Do not use numbers you have not measured.
