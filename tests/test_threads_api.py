"""Threads API 測試：用 responses 套件攔截 HTTP，完全不會連到真正的 Threads。"""

import pytest
import requests
import responses
from responses import matchers

from bot.threads_api import (
    API_BASE,
    GRAPH_BASE,
    ThreadsAPIError,
    ThreadsClient,
    TokenExpiredError,
    refresh_long_lived_token,
)

TOKEN = "fake-token"


def make_client():
    return ThreadsClient(TOKEN, sleep=lambda _: None)  # 不真的等待


@responses.activate
def test_publish_text_success():
    responses.post(
        f"{API_BASE}/me/threads",
        json={"id": "c1"},
        match=[matchers.urlencoded_params_matcher(
            {"media_type": "TEXT", "text": "哈囉", "access_token": TOKEN})],
    )
    responses.get(f"{API_BASE}/c1", json={"status": "FINISHED", "id": "c1"})
    responses.post(
        f"{API_BASE}/me/threads_publish",
        json={"id": "p1"},
        match=[matchers.urlencoded_params_matcher({"creation_id": "c1", "access_token": TOKEN})],
    )
    assert make_client().publish_text("哈囉") == "p1"


@responses.activate
def test_wait_until_ready_polls_until_finished():
    responses.get(f"{API_BASE}/c1", json={"status": "IN_PROGRESS"})
    responses.get(f"{API_BASE}/c1", json={"status": "FINISHED"})
    make_client().wait_until_ready("c1")
    assert len(responses.calls) == 2


@responses.activate
def test_wait_until_ready_error_status():
    responses.get(f"{API_BASE}/c1", json={"status": "ERROR", "error_message": "bad"})
    with pytest.raises(ThreadsAPIError, match="ERROR"):
        make_client().wait_until_ready("c1")


@responses.activate
def test_wait_until_ready_timeout():
    responses.get(f"{API_BASE}/c1", json={"status": "IN_PROGRESS"})
    with pytest.raises(ThreadsAPIError, match="逾時"):
        make_client().wait_until_ready("c1", attempts=3)


@responses.activate
def test_expired_token_raises_token_error():
    responses.post(
        f"{API_BASE}/me/threads",
        status=400,
        json={"error": {"message": "Error validating access token: Session has expired",
                        "type": "OAuthException", "code": 190, "error_subcode": 463}},
    )
    with pytest.raises(TokenExpiredError) as exc_info:
        make_client().publish_text("hi")
    message = str(exc_info.value)
    assert "過期或無效" in message
    assert "README" in message
    assert TOKEN not in message  # 錯誤訊息不能洩漏 token


@responses.activate
def test_rate_limit_error():
    responses.post(f"{API_BASE}/me/threads", status=429,
                   json={"error": {"message": "limit", "code": 4}})
    with pytest.raises(ThreadsAPIError, match="呼叫上限"):
        make_client().publish_text("hi")


@responses.activate
def test_permission_error():
    responses.post(f"{API_BASE}/me/threads", status=403,
                   json={"error": {"message": "no perm", "code": 10}})
    with pytest.raises(ThreadsAPIError, match="threads_content_publish"):
        make_client().publish_text("hi")


@responses.activate
def test_non_json_error_response():
    responses.post(f"{API_BASE}/me/threads", status=502, body="Bad Gateway")
    with pytest.raises(ThreadsAPIError, match="HTTP 502"):
        make_client().publish_text("hi")


@responses.activate
def test_network_error_does_not_leak_token():
    responses.post(f"{API_BASE}/me/threads",
                   body=requests.ConnectionError(f"failed url?access_token={TOKEN}"))
    with pytest.raises(ThreadsAPIError) as exc_info:
        make_client().publish_text("hi")
    assert TOKEN not in str(exc_info.value)
    assert "無法連線" in str(exc_info.value)


def test_missing_token():
    with pytest.raises(TokenExpiredError, match="沒有提供"):
        ThreadsClient("")


@responses.activate
def test_refresh_long_lived_token():
    responses.get(
        f"{GRAPH_BASE}/refresh_access_token",
        json={"access_token": "new", "token_type": "bearer", "expires_in": 5184000},
        match=[matchers.query_param_matcher(
            {"grant_type": "th_refresh_token", "access_token": "old"})],
    )
    assert refresh_long_lived_token("old")["access_token"] == "new"


@responses.activate
def test_refresh_expired_token_fails_clearly():
    responses.get(f"{GRAPH_BASE}/refresh_access_token", status=400,
                  json={"error": {"message": "expired", "code": 190}})
    with pytest.raises(TokenExpiredError):
        refresh_long_lived_token("old")


def test_build_authorize_url():
    from bot.threads_api import build_authorize_url

    url = build_authorize_url("123", "https://localhost/cb")
    assert url.startswith("https://threads.net/oauth/authorize?")
    assert "client_id=123" in url
    assert "threads_content_publish" in url
    assert "redirect_uri=https%3A%2F%2Flocalhost%2Fcb" in url


@responses.activate
def test_exchange_code_strips_suffix():
    from bot.threads_api import exchange_code_for_token

    responses.post(
        f"{GRAPH_BASE}/oauth/access_token",
        json={"access_token": "short", "user_id": 1},
        match=[matchers.urlencoded_params_matcher({
            "client_id": "123", "client_secret": "s", "grant_type": "authorization_code",
            "redirect_uri": "https://localhost/cb", "code": "abc"})],
    )
    assert exchange_code_for_token("123", "s", "https://localhost/cb", "abc#_")["access_token"] == "short"
