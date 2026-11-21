"""本機用的 token 小工具（不會在 GitHub Actions 中執行）。

  python -m bot.token_tool login      # 第一次取得 token：授權 → 直接拿到 60 天長期 token
  python -m bot.token_tool exchange   # 已有短期 token → 60 天長期 token
  python -m bot.token_tool refresh    # 長期 token 續期 60 天
  python -m bot.token_tool check      # 檢查 token 是否有效、對應哪個帳號

token 與 App Secret 用隱藏輸入（getpass），不會留在 shell 歷史紀錄裡。
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime, timedelta
from getpass import getpass

from bot.config import TAIPEI
from bot.threads_api import (
    ThreadsAPIError,
    ThreadsClient,
    build_authorize_url,
    exchange_code_for_token,
    exchange_for_long_lived_token,
    refresh_long_lived_token,
)


def _print_new_token(result: dict) -> None:
    expires_in = int(result.get("expires_in", 0))
    expires_at = (datetime.now(TAIPEI) + timedelta(seconds=expires_in)).date()
    # 保守起見提早一天
    safe_date = expires_at - timedelta(days=1)
    print("\n新的長期 token（請複製到 GitHub Secret THREADS_ACCESS_TOKEN，不要存成檔案）：\n")
    print(result["access_token"])
    print(f"\n有效 {expires_in // 86400} 天。請把 GitHub Variable THREADS_TOKEN_EXPIRES_AT 設為：{safe_date}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Threads token 工具")
    parser.add_argument("action", choices=["login", "exchange", "refresh", "check"])
    args = parser.parse_args(argv)

    try:
        if args.action == "login":
            app_id = input("Threads App ID：").strip()
            redirect_uri = input("Redirect URI（需與 App 設定完全相同）：").strip()
            print("\n請在瀏覽器打開以下網址並按「允許」：\n")
            print(build_authorize_url(app_id, redirect_uri))
            print("\n被導向後，網址列會出現 ?code=xxxx，就算頁面打不開也沒關係，複製 code= 後面的值。")
            code = getpass("貼上 code（不會顯示）：").strip()
            secret = getpass("貼上 Threads App Secret（不會顯示）：").strip()
            short = exchange_code_for_token(app_id, secret, redirect_uri, code)["access_token"]
            _print_new_token(exchange_for_long_lived_token(short, secret))
        elif args.action == "exchange":
            short = getpass("貼上短期 access token（不會顯示）：").strip()
            secret = getpass("貼上 Threads App Secret（不會顯示）：").strip()
            _print_new_token(exchange_for_long_lived_token(short, secret))
        elif args.action == "refresh":
            token = getpass("貼上目前的長期 access token（不會顯示）：").strip()
            _print_new_token(refresh_long_lived_token(token))
        else:
            token = getpass("貼上 access token（不會顯示）：").strip()
            me = ThreadsClient(token).get_me()
            print(f"Token 有效，帳號：@{me.get('username')}（id={me.get('id')}）")
    except ThreadsAPIError as exc:
        print(f"[錯誤] {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
