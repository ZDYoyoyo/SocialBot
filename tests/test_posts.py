import json
from datetime import datetime

import pytest

from bot import posts as P
from bot.config import TAIPEI
from tests.conftest import make_post


def test_format_post_appends_hashtags():
    post = make_post(1, content="  內文  ", hashtags=["Java", "#SpringBoot"])
    assert P.format_post(post) == "內文\n\n#Java #SpringBoot"


def test_format_post_without_hashtags():
    assert P.format_post(make_post(1, content="內文", hashtags=[])) == "內文"


def test_text_length_counts_emoji_as_two():
    assert P.text_length("中文abc") == 5
    assert P.text_length("😀") == 2


def test_select_next_skips_published_and_too_long():
    posts = [
        make_post(1, published=True),
        make_post(2, content="字" * 600),
        make_post(3),
        make_post(4),
    ]
    post, skipped = P.select_next(posts)
    assert post["id"] == 3
    assert [s.post["id"] for s in skipped] == [2]
    assert skipped[0].length > P.THREADS_MAX_CHARS


def test_length_limit_includes_hashtags():
    # 內文剛好 500，加上 hashtag 就超過
    post = make_post(1, content="字" * 500, hashtags=["Java"])
    assert P.select_next([post]) == (None, [P.SkippedPost(post, 507)])


def test_select_next_returns_none_when_all_published():
    assert P.select_next([make_post(1, published=True)]) == (None, [])


def test_unpublished_count_ignores_too_long():
    posts = [make_post(1), make_post(2, content="字" * 600), make_post(3, published=True)]
    assert P.unpublished_count(posts) == 1


def test_mark_published():
    post = make_post(1)
    P.mark_published(post, "999", datetime(2026, 11, 22, 8, 7, 13, tzinfo=TAIPEI))
    assert post["published"] is True
    assert post["published_at"] == "2026-11-22T08:07:13+08:00"
    assert post["threads_post_id"] == "999"


def test_load_and_save_roundtrip(write_posts):
    path = write_posts([make_post(1), make_post(2)])
    posts = P.load_posts(path)
    posts[0]["published"] = True
    P.save_posts(path, posts)
    text = path.read_text(encoding="utf-8")
    assert "第 1 篇內文" in text  # 中文不會被轉成 \uXXXX
    assert json.loads(text)[0]["published"] is True


@pytest.mark.parametrize(
    "bad, message",
    [
        ({"not": "a list"}, "最外層必須是陣列"),
        ([{"id": 1}], "缺少欄位"),
        ([make_post(1), make_post(1)], "重複"),
        ([make_post(1, content="  ")], "content 是空的"),
        ([make_post(1, hashtags=["Spring Boot"])], "hashtag"),
        ([{**make_post(1), "published": "no"}], "published"),
    ],
)
def test_load_posts_validation(write_posts, bad, message):
    path = write_posts(bad)
    with pytest.raises(P.PostsFileError, match=message):
        P.load_posts(path)


def test_load_posts_invalid_json(tmp_path):
    path = tmp_path / "posts.json"
    path.write_text("[{,]", encoding="utf-8")
    with pytest.raises(P.PostsFileError, match="不是合法的 JSON"):
        P.load_posts(path)


def test_load_posts_missing_file(tmp_path):
    with pytest.raises(P.PostsFileError, match="找不到"):
        P.load_posts(tmp_path / "nope.json")


def test_format_post_escapes_annotations_to_avoid_mentions():
    post = make_post(1, content="@Service 與 @Test，信箱 a@b.com 不變", hashtags=[])
    assert P.format_post(post) == "＠Service 與 ＠Test，信箱 a@b.com 不變"
