"""posts.json 的讀寫、挑選與內文組合。

這個模組完全不碰網路，所以最容易測試。
"""

from __future__ import annotations

import json
import os
import re
import tempfile
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

# Threads 單篇貼文的文字上限（官方文件：500 字元）
THREADS_MAX_CHARS = 500

# Threads 會把「@文字」當成標記帳號（@mention），Java 的 @Service、@Test 可能會
# 標記到真實存在的陌生帳號。發文時把這類 @ 換成全形「＠」，posts.json 本身不變。
ESCAPE_MENTIONS = True
_MENTION_RE = re.compile(r"(?<![\w.])@(?=[A-Za-z_])")

REQUIRED_FIELDS = ("id", "topic", "content", "hashtags", "published", "published_at")


class PostsFileError(Exception):
    """posts.json 格式錯誤。"""


@dataclass
class SkippedPost:
    post: dict[str, Any]
    length: int


def load_posts(path: str | Path) -> list[dict[str, Any]]:
    """讀取並驗證 posts.json，回傳文章清單（dict 組成的 list）。"""
    path = Path(path)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise PostsFileError(f"找不到文章檔：{path}") from exc
    except json.JSONDecodeError as exc:
        raise PostsFileError(f"{path} 不是合法的 JSON（第 {exc.lineno} 行）：{exc.msg}") from exc

    if not isinstance(data, list):
        raise PostsFileError(f"{path} 最外層必須是陣列 [ ... ]")

    seen_ids: set[Any] = set()
    for index, post in enumerate(data):
        where = f"第 {index + 1} 篇"
        if not isinstance(post, dict):
            raise PostsFileError(f"{where} 不是物件 {{ ... }}")
        missing = [field for field in REQUIRED_FIELDS if field not in post]
        if missing:
            raise PostsFileError(f"{where} 缺少欄位：{', '.join(missing)}")
        if post["id"] in seen_ids:
            raise PostsFileError(f"{where} 的 id {post['id']!r} 重複了")
        seen_ids.add(post["id"])
        if not isinstance(post["content"], str) or not post["content"].strip():
            raise PostsFileError(f"{where}（id={post['id']}）的 content 是空的")
        if not isinstance(post["hashtags"], list):
            raise PostsFileError(f"{where}（id={post['id']}）的 hashtags 必須是陣列")
        for tag in post["hashtags"]:
            if not isinstance(tag, str) or not tag.strip("#").strip() or any(c.isspace() for c in tag):
                raise PostsFileError(
                    f"{where}（id={post['id']}）的 hashtag {tag!r} 不合法（不可空白或含空格）"
                )
        if not isinstance(post["published"], bool):
            raise PostsFileError(f"{where}（id={post['id']}）的 published 必須是 true 或 false")
    return data


def save_posts(path: str | Path, posts: list[dict[str, Any]]) -> None:
    """寫回 posts.json。

    先寫到暫存檔再改名取代，避免寫到一半當掉時把原檔弄壞。
    """
    path = Path(path)
    text = json.dumps(posts, ensure_ascii=False, indent=2) + "\n"
    fd, tmp_name = tempfile.mkstemp(dir=path.parent, prefix=".posts-", suffix=".json")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as tmp:
            tmp.write(text)
        os.replace(tmp_name, path)
    except BaseException:
        Path(tmp_name).unlink(missing_ok=True)
        raise


def format_post(post: dict[str, Any]) -> str:
    """組合實際要發出去的文字：內文 + 空行 + hashtags。"""
    body = post["content"].strip()
    if ESCAPE_MENTIONS:
        body = escape_mentions(body)
    tags = " ".join("#" + tag.lstrip("#") for tag in post["hashtags"])
    return f"{body}\n\n{tags}" if tags else body


def escape_mentions(text: str) -> str:
    """把 @Service 變成 ＠Service；email（a@b.com）不受影響。"""
    return _MENTION_RE.sub("＠", text)


def text_length(text: str) -> int:
    """計算長度（保守算法）。

    Python 的 len() 算的是 Unicode 字元數，但有些平台會把 emoji 等字元算成 2。
    這裡用 UTF-16 單位數計算：一般中英文字算 1，emoji 算 2，
    結果只會 >= len()，寧可多算也不要被 Threads 拒絕。
    """
    return len(text.encode("utf-16-le")) // 2


def is_within_limit(text: str, limit: int = THREADS_MAX_CHARS) -> bool:
    return text_length(text) <= limit


def select_next(posts: list[dict[str, Any]]) -> tuple[dict[str, Any] | None, list[SkippedPost]]:
    """依序找第一篇「未發布且長度合格」的文章。

    回傳 (要發的文章或 None, 途中因太長被跳過的文章清單)。
    """
    skipped: list[SkippedPost] = []
    for post in posts:
        if post["published"]:
            continue
        length = text_length(format_post(post))
        if length > THREADS_MAX_CHARS:
            skipped.append(SkippedPost(post=post, length=length))
            continue
        return post, skipped
    return None, skipped


def unpublished_count(posts: list[dict[str, Any]]) -> int:
    """還沒發布、而且長度合格（之後真的發得出去）的文章數。"""
    return sum(
        1 for p in posts if not p["published"] and is_within_limit(format_post(p))
    )


def mark_published(post: dict[str, Any], threads_post_id: str, when: datetime) -> None:
    """把文章標記為已發布（直接修改傳入的 dict）。"""
    post["published"] = True
    post["published_at"] = when.isoformat(timespec="seconds")
    post["threads_post_id"] = threads_post_id
