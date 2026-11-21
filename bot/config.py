"""從環境變數讀取設定。機密一律只從環境變數來，不寫在程式裡。"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta, timezone
from typing import Mapping

TAIPEI = timezone(timedelta(hours=8), name="Asia/Taipei")  # 台灣沒有日光節約時間

# 剩幾篇以下就開 Issue 提醒補文章（「少於 5 篇」= 剩 0~4 篇）
LOW_POSTS_THRESHOLD = 5
# token 剩幾天以內就開 Issue 提醒續期
TOKEN_WARN_DAYS = 10


class ConfigError(Exception):
    pass


@dataclass(frozen=True)
class Config:
    threads_token: str | None
    token_expires_at: date | None
    github_token: str | None
    github_repo: str | None
    in_github_actions: bool
    step_summary_path: str | None

    @classmethod
    def from_env(cls, env: Mapping[str, str]) -> "Config":
        raw_expiry = (env.get("THREADS_TOKEN_EXPIRES_AT") or "").strip()
        expires: date | None = None
        if raw_expiry:
            try:
                expires = date.fromisoformat(raw_expiry)
            except ValueError as exc:
                raise ConfigError(
                    f"THREADS_TOKEN_EXPIRES_AT 格式錯誤：{raw_expiry!r}，應為 YYYY-MM-DD，例如 2027-01-20"
                ) from exc
        return cls(
            threads_token=(env.get("THREADS_ACCESS_TOKEN") or "").strip() or None,
            token_expires_at=expires,
            github_token=env.get("GITHUB_TOKEN") or None,
            github_repo=env.get("GITHUB_REPOSITORY") or None,
            in_github_actions=env.get("GITHUB_ACTIONS") == "true",
            step_summary_path=env.get("GITHUB_STEP_SUMMARY") or None,
        )
