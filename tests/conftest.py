import json

import pytest


def make_post(post_id, *, published=False, content=None, hashtags=("Java", "測試")):
    return {
        "id": post_id,
        "topic": "測試主題",
        "content": content if content is not None else f"第 {post_id} 篇內文",
        "hashtags": list(hashtags),
        "published": published,
        "published_at": "2026-01-01T08:00:00+08:00" if published else None,
        "threads_post_id": "old" if published else None,
    }


@pytest.fixture
def write_posts(tmp_path):
    """寫一份假的 posts.json 到暫存資料夾，回傳路徑。"""

    def _write(posts):
        path = tmp_path / "posts.json"
        path.write_text(json.dumps(posts, ensure_ascii=False), encoding="utf-8")
        return path

    return _write
