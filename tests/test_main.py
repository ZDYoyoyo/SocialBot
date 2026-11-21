"""主流程測試：Threads client 與 GitHub Issue 都換成 Mock。"""

import json
from datetime import datetime
from unittest.mock import Mock

import pytest

from bot.config import TAIPEI
from bot.github_issue import LABEL_NEED_POSTS, LABEL_TOKEN, GitHubIssueError, GitHubIssues
from bot.main import run
from bot.threads_api import ThreadsAPIError, ThreadsClient, TokenExpiredError
from tests.conftest import make_post

NOW = datetime(2026, 11, 22, 8, 7, 0, tzinfo=TAIPEI)
ENV = {"THREADS_ACCESS_TOKEN": "tok", "GITHUB_TOKEN": "gh", "GITHUB_REPOSITORY": "me/repo"}


@pytest.fixture
def client():
    c = Mock(spec=ThreadsClient)
    c.publish_text.return_value = "post-123"
    return c


@pytest.fixture
def issues():
    i = Mock(spec=GitHubIssues)
    i.ensure_issue.return_value = ({"number": 1, "title": "t"}, True)
    return i


def read(path):
    return json.loads(path.read_text(encoding="utf-8"))


def labels(issues):
    return [c.args[2] for c in issues.ensure_issue.call_args_list]


def test_publishes_first_unpublished(write_posts, client, issues):
    path = write_posts([make_post(1, published=True)] + [make_post(i) for i in range(2, 9)])
    code = run(["--posts", str(path)], env=ENV, now=NOW, threads_client=client, issues=issues)

    assert code == 0
    client.publish_text.assert_called_once_with("第 2 篇內文\n\n#Java #測試")
    saved = read(path)
    assert saved[1]["published"] is True
    assert saved[1]["published_at"] == "2026-11-22T08:07:00+08:00"
    assert saved[1]["threads_post_id"] == "post-123"
    assert saved[2]["published"] is False
    issues.ensure_issue.assert_not_called()  # 還剩 6 篇，不用提醒


def test_dry_run_does_not_publish_or_modify(write_posts, client, issues, capsys):
    path = write_posts([make_post(1), make_post(2)])
    before = path.read_text(encoding="utf-8")
    code = run(["--dry-run", "--posts", str(path)], env={}, now=NOW,
               threads_client=client, issues=issues)

    assert code == 0
    client.publish_text.assert_not_called()
    issues.ensure_issue.assert_not_called()
    assert path.read_text(encoding="utf-8") == before
    out = capsys.readouterr().out
    assert "DRY RUN" in out
    assert "id=1" in out
    assert "第 1 篇內文" in out


def test_opens_issue_when_fewer_than_5_left(write_posts, client, issues):
    path = write_posts([make_post(i) for i in range(1, 6)])  # 5 篇，發完剩 4 篇
    assert run(["--posts", str(path)], env=ENV, now=NOW, threads_client=client, issues=issues) == 0
    assert labels(issues) == [LABEL_NEED_POSTS]
    assert "4" in issues.ensure_issue.call_args.args[0]


def test_no_issue_when_exactly_5_left(write_posts, client, issues):
    path = write_posts([make_post(i) for i in range(1, 7)])  # 6 篇，發完剩 5 篇
    run(["--posts", str(path)], env=ENV, now=NOW, threads_client=client, issues=issues)
    issues.ensure_issue.assert_not_called()


def test_skips_too_long_post_and_warns(write_posts, client, issues, capsys):
    path = write_posts([make_post(1, content="字" * 600)] + [make_post(i) for i in range(2, 9)])
    assert run(["--posts", str(path)], env=ENV, now=NOW, threads_client=client, issues=issues) == 0
    assert client.publish_text.call_args.args[0].startswith("第 2 篇")
    out = capsys.readouterr().out
    assert "id=1" in out and "超過上限" in out
    assert read(path)[0]["published"] is False  # 太長的文章保持未發布，等你修改


def test_no_posts_left(write_posts, client, issues):
    path = write_posts([make_post(1, published=True)])
    assert run(["--posts", str(path)], env=ENV, now=NOW, threads_client=client, issues=issues) == 0
    client.publish_text.assert_not_called()
    assert labels(issues) == [LABEL_NEED_POSTS]


def test_token_expired_fails_and_opens_issue(write_posts, client, issues, capsys):
    client.publish_text.side_effect = TokenExpiredError("Threads access token 已過期或無效")
    path = write_posts([make_post(i) for i in range(1, 9)])
    before = path.read_text(encoding="utf-8")

    assert run(["--posts", str(path)], env=ENV, now=NOW, threads_client=client, issues=issues) == 1
    assert path.read_text(encoding="utf-8") == before  # 失敗時不改檔
    assert labels(issues) == [LABEL_TOKEN]
    assert "已過期或無效" in capsys.readouterr().err


def test_other_api_error_fails_without_saving(write_posts, client, issues):
    client.publish_text.side_effect = ThreadsAPIError("boom")
    path = write_posts([make_post(i) for i in range(1, 9)])
    before = path.read_text(encoding="utf-8")
    assert run(["--posts", str(path)], env=ENV, now=NOW, threads_client=client, issues=issues) == 1
    assert path.read_text(encoding="utf-8") == before


def test_warns_when_token_expires_soon(write_posts, client, issues):
    path = write_posts([make_post(i) for i in range(1, 9)])
    env = {**ENV, "THREADS_TOKEN_EXPIRES_AT": "2026-11-30"}  # 剩 8 天
    assert run(["--posts", str(path)], env=env, now=NOW, threads_client=client, issues=issues) == 0
    assert labels(issues) == [LABEL_TOKEN]
    client.publish_text.assert_called_once()  # 還沒過期，照常發文


def test_no_token_warning_when_far_from_expiry(write_posts, client, issues):
    path = write_posts([make_post(i) for i in range(1, 9)])
    env = {**ENV, "THREADS_TOKEN_EXPIRES_AT": "2027-01-15"}
    run(["--posts", str(path)], env=env, now=NOW, threads_client=client, issues=issues)
    issues.ensure_issue.assert_not_called()


def test_bad_expiry_format(write_posts, client):
    path = write_posts([make_post(1)])
    env = {**ENV, "THREADS_TOKEN_EXPIRES_AT": "2027/01/15"}
    assert run(["--posts", str(path)], env=env, now=NOW, threads_client=client) == 1
    client.publish_text.assert_not_called()


def test_issue_failure_does_not_fail_run(write_posts, client, issues):
    issues.ensure_issue.side_effect = GitHubIssueError("403")
    path = write_posts([make_post(1), make_post(2)])
    assert run(["--posts", str(path)], env=ENV, now=NOW, threads_client=client, issues=issues) == 0
    assert read(path)[0]["published"] is True


def test_invalid_posts_file(tmp_path, client):
    path = tmp_path / "posts.json"
    path.write_text("not json", encoding="utf-8")
    assert run(["--posts", str(path)], env=ENV, now=NOW, threads_client=client) == 1


def test_github_actions_annotations_and_summary(write_posts, client, issues, tmp_path, capsys):
    summary = tmp_path / "summary.md"
    path = write_posts([make_post(1, content="字" * 600)] + [make_post(i) for i in range(2, 9)])
    env = {**ENV, "GITHUB_ACTIONS": "true", "GITHUB_STEP_SUMMARY": str(summary)}
    run(["--posts", str(path)], env=env, now=NOW, threads_client=client, issues=issues)
    assert "::warning::" in capsys.readouterr().out
    text = summary.read_text(encoding="utf-8")
    assert "已發布 id=2" in text
