"""Download failed GitHub Actions job logs from public repositories.

Needs a token (GITHUB_TOKEN). GitHub requires authentication to download logs.
The log endpoint redirects to a pre-signed URL; we follow it WITHOUT sending
the token to the second host.
"""
from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from pathlib import Path

API = "https://api.github.com"
UA = "ci-failure-explainer"


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):  # noqa: D401
        return None


def _headers(token: str | None) -> dict:
    h = {"Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28",
         "User-Agent": UA}
    if token:
        h["Authorization"] = f"Bearer {token}"
    return h


def _open(url: str, token: str | None) -> tuple[bytes, str | None]:
    """Return (body, redirect_location). Does not follow redirects."""
    opener = urllib.request.build_opener(_NoRedirect)
    req = urllib.request.Request(url, headers=_headers(token))
    try:
        with opener.open(req, timeout=30) as r:
            return r.read(), None
    except urllib.error.HTTPError as e:
        if e.code in (301, 302, 303, 307, 308):
            return b"", e.headers.get("Location")
        raise


def get_json(url: str, token: str | None) -> dict:
    body, _ = _open(url, token)
    return json.loads(body)


def get_log_text(url: str, token: str | None) -> str:
    body, location = _open(url, token)
    if location:
        req = urllib.request.Request(location, headers={"User-Agent": UA})
        with urllib.request.urlopen(req, timeout=60) as r:
            return r.read().decode("utf-8", "replace")
    return body.decode("utf-8", "replace")


def list_failed_runs(repo: str, token: str | None, limit: int) -> list[dict]:
    data = get_json(f"{API}/repos/{repo}/actions/runs?status=failure&per_page={min(limit, 100)}", token)
    return data.get("workflow_runs", [])[:limit]


def list_failed_jobs(repo: str, run_id: int, token: str | None) -> list[dict]:
    data = get_json(f"{API}/repos/{repo}/actions/runs/{run_id}/jobs?filter=latest&per_page=100", token)
    return [j for j in data.get("jobs", []) if j.get("conclusion") == "failure"]


def fetch_failed_logs(repo: str, token: str | None, limit: int, out_dir: str | Path,
                      pause_s: float = 0.5) -> Path:
    """Save logs and write a `labeled.todo.jsonl` template for hand labeling."""
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    manifest = out / "labeled.todo.jsonl"
    count = 0
    with manifest.open("a", encoding="utf-8") as mf:
        for run in list_failed_runs(repo, token, limit):
            for job in list_failed_jobs(repo, run["id"], token):
                name = f"{repo.replace('/', '_')}_{run['id']}_{job['id']}.log"
                try:
                    text = get_log_text(f"{API}/repos/{repo}/actions/jobs/{job['id']}/logs", token)
                except urllib.error.HTTPError as e:
                    print(f"skip job {job['id']}: HTTP {e.code}")
                    continue
                (out / name).write_text(text, encoding="utf-8")
                mf.write(json.dumps({
                    "id": name.removesuffix(".log"), "log_path": name,
                    "source_url": job.get("html_url", ""),
                    "true_category": "", "fix_keywords": [], "notes": "",
                }) + "\n")
                count += 1
                time.sleep(pause_s)
                if count >= limit:
                    return manifest
    return manifest
