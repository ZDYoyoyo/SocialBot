"""程式進入點：python -m bot.main [--dry-run] [--posts posts.json]

結束代碼：0 = 成功（含 dry-run、沒文章可發）；1 = 失敗。
"""

from __future__ import annotations

import argparse
import os
import sys
from datetime import date, datetime
from pathlib import Path
from typing import Any, Mapping, Sequence

from bot import posts as posts_mod
from bot.config import LOW_POSTS_THRESHOLD, TAIPEI, TOKEN_WARN_DAYS, Config, ConfigError
from bot.github_issue import LABEL_NEED_POSTS, LABEL_TOKEN, GitHubIssueError, GitHubIssues
from bot.threads_api import TOKEN_HELP, ThreadsAPIError, ThreadsClient, TokenExpiredError

DEFAULT_POSTS_PATH = Path(__file__).resolve().parent.parent / "posts.json"


class Reporter:
    """統一輸出：本機印到終端機；在 GitHub Actions 上額外產生警告標記與 Job Summary。"""

    def __init__(self, config: Config):
        self._config = config
        self._summary: list[str] = []

    def info(self, msg: str) -> None:
        print(msg)

    def warning(self, msg: str) -> None:
        print(f"::warning::{msg}" if self._config.in_github_actions else f"[警告] {msg}")
        self._summary.append(f"> ⚠️ {msg}")

    def error(self, msg: str) -> None:
        print(f"::error::{msg}" if self._config.in_github_actions else f"[錯誤] {msg}", file=sys.stderr)
        self._summary.append(f"> ❌ {msg}")

    def summary(self, line: str) -> None:
        self._summary.append(line)

    def flush_summary(self) -> None:
        if self._config.step_summary_path and self._summary:
            with open(self._config.step_summary_path, "a", encoding="utf-8") as fh:
                fh.write("\n\n".join(self._summary) + "\n")


def parse_args(argv: Sequence[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Threads 每日自動發文")
    parser.add_argument("--dry-run", action="store_true", help="只顯示今天要發哪一篇，不實際發文、不改檔案")
    parser.add_argument("--posts", type=Path, default=DEFAULT_POSTS_PATH, help="文章檔路徑（預設 posts.json）")
    return parser.parse_args(argv)


def run(
    argv: Sequence[str] | None = None,
    *,
    env: Mapping[str, str] | None = None,
    now: datetime | None = None,
    threads_client: ThreadsClient | None = None,
    issues: GitHubIssues | None = None,
) -> int:
    """主流程。參數都可以從外部注入，方便測試。"""
    args = parse_args(argv)
    env = os.environ if env is None else env
    now = now or datetime.now(TAIPEI)

    try:
        config = Config.from_env(env)
    except ConfigError as exc:
        print(f"[錯誤] {exc}", file=sys.stderr)
        return 1
    report = Reporter(config)
    try:
        return _run(args, config, report, now, threads_client, issues)
    finally:
        report.flush_summary()


def _run(
    args: argparse.Namespace,
    config: Config,
    report: Reporter,
    now: datetime,
    threads_client: ThreadsClient | None,
    issues: GitHubIssues | None,
) -> int:
    # 1. 讀文章
    try:
        all_posts = posts_mod.load_posts(args.posts)
    except posts_mod.PostsFileError as exc:
        report.error(str(exc))
        return 1

    # 2. 挑出今天要發的文章，順便回報太長被跳過的
    post, skipped = posts_mod.select_next(all_posts)
    for item in skipped:
        report.warning(
            f"文章 id={item.post['id']} 長度 {item.length} 超過上限 {posts_mod.THREADS_MAX_CHARS}，已跳過，請修改後再發"
        )

    if args.dry_run:
        return _dry_run(post, all_posts, config, report, now)

    def open_issue(title: str, body: str, label: str) -> None:
        nonlocal issues
        try:
            if issues is None:
                issues = GitHubIssues(config.github_token or "", config.github_repo or "")
            issue, created = issues.ensure_issue(title, body, label)
            state = "已建立" if created else "已存在"
            report.info(f"提醒 Issue {state}：#{issue.get('number')} {issue.get('title')}")
        except GitHubIssueError as exc:
            # 開 Issue 失敗不應影響發文結果，只記警告
            report.warning(f"無法建立提醒 Issue：{exc}")

    # 3. token 到期提醒
    _check_token_expiry(config, report, now.date(), open_issue)

    # 4. 沒文章可發
    if post is None:
        report.warning("沒有可發布的文章了！請到 posts.json 補充新文章。")
        report.summary("### 今天沒有發文：沒有可發布的文章")
        _remind_low_posts(0, open_issue)
        return 0

    # 5. 發文
    text = posts_mod.format_post(post)
    report.info(f"準備發布 id={post['id']}（{post['topic']}），長度 {posts_mod.text_length(text)}")
    try:
        client = threads_client or ThreadsClient(config.threads_token or "")
        threads_post_id = client.publish_text(text)
    except TokenExpiredError as exc:
        report.error(str(exc))
        open_issue(
            "🔑 Threads access token 已失效，今日發文失敗",
            f"錯誤訊息：\n\n```\n{exc}\n```\n\n{TOKEN_HELP}\n\n更新後可在 Actions 頁面手動執行 Daily Threads Post 補發。",
            LABEL_TOKEN,
        )
        return 1
    except ThreadsAPIError as exc:
        report.error(f"發文失敗（文章 id={post['id']}）：{exc}")
        return 1

    # 6. 成功後立刻存檔，避免之後步驟失敗造成重複發文
    posts_mod.mark_published(post, threads_post_id, now)
    posts_mod.save_posts(args.posts, all_posts)
    report.info(f"✅ 發文成功！Threads 貼文 id={threads_post_id}")
    report.summary(
        f"### ✅ 已發布 id={post['id']}（{post['topic']}）\n\nThreads 貼文 id：`{threads_post_id}`\n\n"
        f"```\n{text}\n```"
    )

    # 7. 剩餘文章檢查
    remaining = posts_mod.unpublished_count(all_posts)
    report.info(f"剩餘未發布文章：{remaining} 篇")
    if remaining < LOW_POSTS_THRESHOLD:
        _remind_low_posts(remaining, open_issue)
    return 0


def _dry_run(post: dict[str, Any] | None, all_posts: list[dict[str, Any]], config: Config,
             report: Reporter, now: datetime) -> int:
    remaining = posts_mod.unpublished_count(all_posts)
    report.info("=== DRY RUN：不會實際發文，也不會修改任何檔案 ===")
    if post is None:
        report.info("沒有可發布的文章。")
        report.summary("### DRY RUN：沒有可發布的文章")
        return 0
    text = posts_mod.format_post(post)
    report.info(f"今天會發布：id={post['id']}（{post['topic']}）")
    report.info(f"長度：{posts_mod.text_length(text)} / {posts_mod.THREADS_MAX_CHARS}")
    report.info("-" * 40)
    report.info(text)
    report.info("-" * 40)
    report.info(f"發完後剩餘未發布：{remaining - 1} 篇")
    if config.token_expires_at:
        days = (config.token_expires_at - now.date()).days
        report.info(f"Token 到期日：{config.token_expires_at}（剩 {days} 天）")
    report.summary(f"### DRY RUN：今天會發布 id={post['id']}（{post['topic']}）\n\n```\n{text}\n```")
    return 0


def _check_token_expiry(config: Config, report: Reporter, today: date, open_issue) -> None:
    if config.token_expires_at is None:
        report.info("未設定 THREADS_TOKEN_EXPIRES_AT，無法提前提醒 token 到期（建議設定，見 README）")
        return
    days_left = (config.token_expires_at - today).days
    if days_left > TOKEN_WARN_DAYS:
        report.info(f"Token 剩 {days_left} 天到期")
        return
    if days_left < 0:
        msg = f"Threads token 已於 {config.token_expires_at} 到期"
    else:
        msg = f"Threads token 將在 {days_left} 天後（{config.token_expires_at}）到期"
    report.warning(f"{msg}。{TOKEN_HELP}")
    open_issue(
        f"🔑 {msg}，請續期",
        f"{msg}。\n\n{TOKEN_HELP}\n\n本機執行：`python -m bot.token_tool refresh`\n\n更新完成後可直接關閉此 Issue。",
        LABEL_TOKEN,
    )


def _remind_low_posts(remaining: int, open_issue) -> None:
    open_issue(
        f"📝 posts.json 只剩 {remaining} 篇未發布文章，請補充",
        f"目前只剩 **{remaining}** 篇未發布文章（門檻：少於 {LOW_POSTS_THRESHOLD} 篇）。\n\n"
        "請依 README「如何新增文章」補充 posts.json，補完後可關閉此 Issue。",
        LABEL_NEED_POSTS,
    )


def main() -> None:
    sys.exit(run())


if __name__ == "__main__":
    main()
