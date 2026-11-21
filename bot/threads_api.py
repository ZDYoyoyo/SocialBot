"""官方 Threads Graph API 的最小封裝。

文件：https://developers.facebook.com/docs/threads
發一篇純文字貼文需要兩步：
  1. POST /me/threads          （建立「媒體容器」，拿到 creation id）
  2. POST /me/threads_publish  （把容器正式發布，拿到貼文 id）
"""

from __future__ import annotations

import time
from urllib.parse import urlencode
from typing import Any, Callable

import requests

GRAPH_BASE = "https://graph.threads.net"
API_VERSION = "v1.0"
API_BASE = f"{GRAPH_BASE}/{API_VERSION}"

# Meta 用 190 代表 access token 無效或過期
TOKEN_ERROR_CODE = 190

TOKEN_HELP = (
    "請依 README 的「更新長期 Token」步驟產生新 token，"
    "並更新 GitHub Secret THREADS_ACCESS_TOKEN 與 Variable THREADS_TOKEN_EXPIRES_AT。"
)


class ThreadsAPIError(Exception):
    """呼叫 Threads API 失敗。"""

    def __init__(self, message: str, *, code: int | None = None, status: int | None = None):
        super().__init__(message)
        self.code = code
        self.status = status


class TokenExpiredError(ThreadsAPIError):
    """Access token 過期、被撤銷或無效。"""


class ThreadsClient:
    def __init__(
        self,
        access_token: str,
        *,
        session: requests.Session | None = None,
        timeout: float = 30,
        sleep: Callable[[float], None] = time.sleep,
    ):
        if not access_token:
            raise TokenExpiredError("沒有提供 Threads access token。" + TOKEN_HELP)
        self._token = access_token
        self._session = session or requests.Session()
        self._timeout = timeout
        self._sleep = sleep  # 測試時可以換成假的，避免真的等待

    # ---- 底層 HTTP ----------------------------------------------------

    def _request(self, method: str, url: str, params: dict[str, Any]) -> dict[str, Any]:
        params = {**params, "access_token": self._token}
        try:
            # POST 時參數放在 body（data=）而不是網址，減少 token 出現在 log 的機會
            if method == "GET":
                resp = self._session.get(url, params=params, timeout=self._timeout)
            else:
                resp = self._session.post(url, data=params, timeout=self._timeout)
        except requests.RequestException as exc:
            # 注意：不要把 exc 原文印出，裡面可能含有帶 token 的網址
            raise ThreadsAPIError(f"無法連線到 Threads API（{type(exc).__name__}），請稍後再試") from None

        try:
            payload = resp.json()
        except ValueError:
            payload = {}

        if resp.ok and "error" not in payload:
            return payload
        raise _build_error(resp.status_code, payload)

    # ---- 公開方法 ------------------------------------------------------

    def get_me(self) -> dict[str, Any]:
        """取得目前 token 對應的帳號資訊，可用來檢查 token 是否有效。"""
        return self._request("GET", f"{API_BASE}/me", {"fields": "id,username"})

    def create_text_container(self, text: str) -> str:
        data = self._request("POST", f"{API_BASE}/me/threads", {"media_type": "TEXT", "text": text})
        container_id = data.get("id")
        if not container_id:
            raise ThreadsAPIError(f"建立貼文容器失敗，回應中沒有 id：{data}")
        return str(container_id)

    def wait_until_ready(self, container_id: str, *, attempts: int = 5, interval: float = 3) -> None:
        """等待容器狀態變成 FINISHED（純文字通常立即完成）。"""
        status = "UNKNOWN"
        for attempt in range(attempts):
            data = self._request(
                "GET", f"{API_BASE}/{container_id}", {"fields": "status,error_message"}
            )
            status = data.get("status", "UNKNOWN")
            if status == "FINISHED":
                return
            if status in ("ERROR", "EXPIRED"):
                raise ThreadsAPIError(
                    f"貼文容器狀態為 {status}：{data.get('error_message', '沒有更多說明')}"
                )
            if attempt < attempts - 1:
                self._sleep(interval)
        raise ThreadsAPIError(f"等待貼文容器就緒逾時（最後狀態：{status}）")

    def publish_container(self, container_id: str) -> str:
        data = self._request("POST", f"{API_BASE}/me/threads_publish", {"creation_id": container_id})
        post_id = data.get("id")
        if not post_id:
            raise ThreadsAPIError(f"發布失敗，回應中沒有貼文 id：{data}")
        return str(post_id)

    def publish_text(self, text: str) -> str:
        """一次完成兩步驟發文，回傳 Threads 貼文 id。"""
        container_id = self.create_text_container(text)
        self.wait_until_ready(container_id)
        return self.publish_container(container_id)


def _build_error(status: int, payload: dict[str, Any]) -> ThreadsAPIError:
    error = payload.get("error") or {}
    code = error.get("code")
    message = error.get("message") or f"HTTP {status}"
    detail = f"{message}（HTTP {status}, code={code}, subcode={error.get('error_subcode')}）"

    if code == TOKEN_ERROR_CODE or (status == 401 and code is None):
        return TokenExpiredError(
            f"Threads access token 已過期或無效：{detail}。{TOKEN_HELP}", code=code, status=status
        )
    if code in (4, 17, 32, 613) or status == 429:
        return ThreadsAPIError(f"已達 Threads API 呼叫上限，請稍後再試：{detail}", code=code, status=status)
    if code == 10 or (code is not None and 200 <= code <= 299):
        return ThreadsAPIError(
            f"權限不足，請確認 App 已取得 threads_basic 與 threads_content_publish 權限：{detail}",
            code=code,
            status=status,
        )
    return ThreadsAPIError(f"Threads API 錯誤：{detail}", code=code, status=status)


# ---- Token 工具（給 bot/token_tool.py 使用） ----------------------------


AUTHORIZE_URL = "https://threads.net/oauth/authorize"
SCOPES = "threads_basic,threads_content_publish"


def build_authorize_url(app_id: str, redirect_uri: str) -> str:
    """產生授權網址：在瀏覽器打開並按「允許」後，會被導向 redirect_uri?code=..."""
    query = urlencode(
        {"client_id": app_id, "redirect_uri": redirect_uri, "scope": SCOPES, "response_type": "code"}
    )
    return f"{AUTHORIZE_URL}?{query}"


def exchange_code_for_token(
    app_id: str, app_secret: str, redirect_uri: str, code: str, *, session: requests.Session | None = None
) -> dict[str, Any]:
    """把授權碼（code）換成 1 小時效期的短期 token。"""
    session = session or requests.Session()
    code = code.strip().removesuffix("#_")  # Threads 會在 code 後面加上 #_
    try:
        resp = session.post(
            f"{GRAPH_BASE}/oauth/access_token",
            data={
                "client_id": app_id,
                "client_secret": app_secret,
                "grant_type": "authorization_code",
                "redirect_uri": redirect_uri,
                "code": code,
            },
            timeout=30,
        )
    except requests.RequestException as exc:
        raise ThreadsAPIError(f"無法連線到 Threads API（{type(exc).__name__}）") from None
    try:
        payload = resp.json()
    except ValueError:
        payload = {}
    if resp.ok and "access_token" in payload:
        return payload
    raise _build_error(resp.status_code, payload)


def exchange_for_long_lived_token(
    short_lived_token: str, app_secret: str, *, session: requests.Session | None = None
) -> dict[str, Any]:
    """把 1 小時效期的短期 token 換成 60 天的長期 token。"""
    session = session or requests.Session()
    return _token_call(
        session,
        f"{GRAPH_BASE}/access_token",
        {"grant_type": "th_exchange_token", "client_secret": app_secret, "access_token": short_lived_token},
    )


def refresh_long_lived_token(
    long_lived_token: str, *, session: requests.Session | None = None
) -> dict[str, Any]:
    """延長長期 token 效期（token 需未過期，且至少已發出 24 小時）。"""
    session = session or requests.Session()
    return _token_call(
        session,
        f"{GRAPH_BASE}/refresh_access_token",
        {"grant_type": "th_refresh_token", "access_token": long_lived_token},
    )


def _token_call(session: requests.Session, url: str, params: dict[str, Any]) -> dict[str, Any]:
    try:
        resp = session.get(url, params=params, timeout=30)
    except requests.RequestException as exc:
        raise ThreadsAPIError(f"無法連線到 Threads API（{type(exc).__name__}）") from None
    try:
        payload = resp.json()
    except ValueError:
        payload = {}
    if resp.ok and "access_token" in payload:
        return payload
    raise _build_error(resp.status_code, payload)
