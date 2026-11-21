"""檢查 repo 裡真正的 posts.json：格式正確、每篇都不超過長度上限。

新增文章後跑 pytest，就能在 push 前發現問題。
"""

from pathlib import Path

from bot import posts as P

POSTS_PATH = Path(__file__).resolve().parent.parent / "posts.json"


def test_repo_posts_json_is_valid():
    posts = P.load_posts(POSTS_PATH)
    assert posts, "posts.json 不應該是空的"


def test_repo_posts_within_threads_limit():
    too_long = [
        (p["id"], P.text_length(P.format_post(p)))
        for p in P.load_posts(POSTS_PATH)
        if not P.is_within_limit(P.format_post(p))
    ]
    assert not too_long, f"以下文章超過 {P.THREADS_MAX_CHARS} 字元（id, 長度）：{too_long}"
