"""用 GitHub REST API 開提醒 Issue。

同一個 label 已經有開著的 Issue 時就不再重開，避免每天洗一張。
"""

from __future__ import annotations

from typing import Any

import requests

GITHUB_API = "https://api.github.com"

LABEL_NEED_POSTS = "need-more-posts"
LABEL_TOKEN = "threads-token"


class GitHubIssueError(Exception):
    pass


class GitHubIssues:
    def __init__(self, token: str, repo: str, *, session: requests.Session | None = None):
        if not token or not repo:
            raise GitHubIssueError("缺少 GITHUB_TOKEN 或 GITHUB_REPOSITORY，無法建立 Issue")
        self._repo = repo
        self._session = session or requests.Session()
        self._headers = {
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }

    def find_open_issue(self, label: str) -> dict[str, Any] | None:
        resp = self._session.get(
            f"{GITHUB_API}/repos/{self._repo}/issues",
            params={"state": "open", "labels": label, "per_page": 1},
            headers=self._headers,
            timeout=30,
        )
        _check(resp, "查詢 Issue")
        issues = resp.json()
        return issues[0] if issues else None

    def ensure_issue(self, title: str, body: str, label: str) -> tuple[dict[str, Any], bool]:
        """確保有一張帶 label 的開啟 Issue。回傳 (issue, 是否為新建)。"""
        existing = self.find_open_issue(label)
        if existing:
            return existing, False
        resp = self._session.post(
            f"{GITHUB_API}/repos/{self._repo}/issues",
            json={"title": title, "body": body, "labels": [label]},
            headers=self._headers,
            timeout=30,
        )
        _check(resp, "建立 Issue")
        return resp.json(), True


def _check(resp: requests.Response, action: str) -> None:
    if not resp.ok:
        raise GitHubIssueError(f"{action}失敗：HTTP {resp.status_code} {resp.text[:200]}")
