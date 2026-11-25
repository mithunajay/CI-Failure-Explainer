"""Download failed GitLab CI job traces (gitlab.com or self-hosted).

Needs GITLAB_TOKEN with read_api scope. `project` is the numeric ID or the
URL-encoded path, e.g. "gitlab-org%2Fgitlab-runner".
"""
from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from pathlib import Path

UA = "ci-failure-explainer"


def _get(url: str, token: str | None) -> bytes:
    headers = {"User-Agent": UA}
    if token:
        headers["PRIVATE-TOKEN"] = token
    with urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=60) as r:
        return r.read()


def fetch_failed_logs(project: str, token: str | None, limit: int, out_dir: str | Path,
                      base_url: str = "https://gitlab.com", pause_s: float = 0.5) -> Path:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    manifest = out / "labeled.todo.jsonl"
    api = f"{base_url.rstrip('/')}/api/v4/projects/{project}"
    jobs = json.loads(_get(f"{api}/jobs?scope[]=failed&per_page={min(limit, 100)}", token))
    count = 0
    with manifest.open("a", encoding="utf-8") as mf:
        for job in jobs[:limit]:
            try:
                text = _get(f"{api}/jobs/{job['id']}/trace", token).decode("utf-8", "replace")
            except urllib.error.HTTPError as e:
                print(f"skip job {job['id']}: HTTP {e.code}")
                continue
            name = f"gitlab_{project.replace('%2F', '_')}_{job['id']}.log"
            (out / name).write_text(text, encoding="utf-8")
            mf.write(json.dumps({
                "id": name.removesuffix(".log"), "log_path": name,
                "source_url": job.get("web_url", ""),
                "true_category": "", "fix_keywords": [], "notes": "",
            }) + "\n")
            count += 1
            time.sleep(pause_s)
    return manifest
