# Labeling guide

Good labels make the evaluation honest. Plan about 2 minutes per log.

## Setup
`ci-explainer fetch-github ...` writes `data/raw/labeled.todo.jsonl` with empty `true_category` fields. Fill these in by hand.

## Fields
- `true_category`: one of `dependency_install, test_failure, lint_format, compile_error, timeout, out_of_memory, network, permission_auth, config_syntax, docker_build, missing_file, unknown`.
- `fix_keywords`: 2 to 5 lowercase words that a correct fix would mention (for example `["requirements", "version"]`). This only powers a lenient automatic proxy.
- `notes`: anything unusual.

## Rules for labeling
1. Label the **root cause**, not the last line. "Process completed with exit code 1" is never the cause.
2. If a Docker build fails because `npm install` failed, the category is `dependency_install`, not `docker_build`.
3. If you cannot tell from the log, label `unknown`. Do not guess.
4. Label before you run the tool, so the model's answer cannot influence you.
5. Prefer logs where you can find the real fix: look at the next commit that turned the pipeline green. That commit is your ground truth for human-graded fix match.
6. Keep a mix: do not label 80 dependency errors. Aim for at least 5 logs per category that appears.
7. Split: label 20 logs first, tune rules or prompts on those, then **do not touch them again**. Report numbers on the remaining logs.

## Human fix grading
After `eval`, open each `results_*.jsonl`. For each row set `human_fix_ok`:
- `true` if the suggested fix would have fixed the real problem (matches what the next green commit changed),
- `false` otherwise.
Then run `ci-explainer summarize --results <file>`.

## Licensing and privacy
Only use public repositories. Respect each project's license and terms. Do not commit raw logs from private projects. The `data/raw/` folder is git-ignored by default; publish only logs you are allowed to share, or publish labels and log URLs instead.
