import pytest
import responses

from bot.github_issue import GITHUB_API, GitHubIssueError, GitHubIssues

REPO = "me/repo"
ISSUES_URL = f"{GITHUB_API}/repos/{REPO}/issues"


@responses.activate
def test_creates_issue_when_none_open():
    responses.get(ISSUES_URL, json=[])
    responses.post(ISSUES_URL, json={"number": 7, "title": "t"}, status=201)
    issue, created = GitHubIssues("tok", REPO).ensure_issue("t", "b", "need-more-posts")
    assert created is True
    assert issue["number"] == 7
    assert responses.calls[1].request.headers["Authorization"] == "Bearer tok"


@responses.activate
def test_does_not_duplicate_open_issue():
    responses.get(ISSUES_URL, json=[{"number": 3, "title": "舊的"}])
    issue, created = GitHubIssues("tok", REPO).ensure_issue("t", "b", "need-more-posts")
    assert created is False
    assert issue["number"] == 3
    assert len(responses.calls) == 1  # 沒有 POST


@responses.activate
def test_api_failure_raises():
    responses.get(ISSUES_URL, status=403, body="forbidden")
    with pytest.raises(GitHubIssueError, match="403"):
        GitHubIssues("tok", REPO).ensure_issue("t", "b", "x")


def test_missing_credentials():
    with pytest.raises(GitHubIssueError):
        GitHubIssues("", REPO)
