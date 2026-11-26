import base64
import hashlib
import importlib
import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient


PASSWORD = "correct horse battery"
PNG_BYTES = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk"
    "/wcAAusB9Wl2nWQAAAAASUVORK5CYII="
)


@pytest.fixture
def posts_app(tmp_path, monkeypatch):
    db_path = tmp_path / "posts.sqlite3"
    monkeypatch.setenv("ZHIJI_DB_PATH", str(db_path))
    monkeypatch.setenv("ZHIJI_UPLOAD_DIR", str(tmp_path / "uploads"))
    monkeypatch.setenv("FRONTEND_ORIGINS", "http://localhost:5173")
    monkeypatch.setenv("SESSION_COOKIE_SECURE", "false")

    import config
    import database
    import main

    importlib.reload(config)
    importlib.reload(database)
    importlib.reload(importlib.import_module("services.room_access"))
    importlib.reload(importlib.import_module("routers.rooms"))
    return importlib.reload(main).app, db_path


@contextmanager
def clients(app, count=3):
    opened = [TestClient(app, base_url="http://testserver") for _ in range(count)]
    try:
        for client in opened:
            client.__enter__()
        yield opened
    finally:
        for client in reversed(opened):
            client.__exit__(None, None, None)


def register(client, username, nickname):
    response = client.post(
        "/api/auth/register",
        json={"username": username, "password": PASSWORD, "nickname": nickname},
    )
    assert response.status_code == 201
    return response.json()


def pair(owner, partner):
    room = owner.post("/api/rooms").json()
    invite = owner.post(f"/api/rooms/{room['id']}/invites").json()["code"]
    joined = partner.post("/api/room-invites/join", json={"code": invite})
    assert joined.status_code == 200
    return room["id"]


def execute(db_path, sql, params=()):
    with sqlite3.connect(db_path) as db:
        cursor = db.execute(sql, params)
        db.commit()
        return cursor.lastrowid


def fetch_one(db_path, sql, params=()):
    with sqlite3.connect(db_path) as db:
        db.row_factory = sqlite3.Row
        return db.execute(sql, params).fetchone()


def fetch_all(db_path, sql, params=()):
    with sqlite3.connect(db_path) as db:
        db.row_factory = sqlite3.Row
        return db.execute(sql, params).fetchall()


def seed_asset(db_path, owner_id, suffix):
    asset_id = f"00000000-0000-4000-8000-{suffix:012d}"
    execute(
        db_path,
        "INSERT INTO media_assets "
        "(id, owner_user_id, storage_key, mime_type, size_bytes) "
        "VALUES (?, ?, ?, 'image/png', 1)",
        (asset_id, owner_id, f"{suffix:032x}.png"),
    )
    return asset_id


def seed_confirmed_diary(db_path, owner_id, text="第一版", *, image_count=2):
    diary_id = execute(
        db_path,
        "INSERT INTO diaries "
        "(date, text, status, confirmed_at, source, user_id) "
        "VALUES ('2026-08-03', ?, 'confirmed', '2026-08-03T10:00:00Z', "
        "'manual', ?)",
        (text, owner_id),
    )
    images = []
    for index in range(image_count):
        suffix = owner_id * 1000 + index + 1
        asset_id = seed_asset(db_path, owner_id, suffix)
        image_id = execute(
            db_path,
            "INSERT INTO images "
            "(diary_id, style, url, kept, asset_id) VALUES (?, 'warm', ?, 1, ?)",
            (diary_id, f"/api/media/{asset_id}", asset_id),
        )
        images.append((image_id, asset_id))
    return diary_id, images


def seed_comic(db_path, owner_id, caption="一周小记"):
    asset_id = seed_asset(db_path, owner_id, owner_id * 1000 + 900)
    comic_id = execute(
        db_path,
        "INSERT INTO weekly_comics "
        "(user_id, week_start, week_end, style, prompt, url, caption, asset_id) "
        "VALUES (?, '2026-07-27', '2026-08-02', 'warm', 'private prompt', ?, ?, ?)",
        (owner_id, f"/api/media/{asset_id}", caption, asset_id),
    )
    return comic_id, asset_id


def publish_diary(client, room_id, diary_id, image_ids):
    return client.put(
        f"/api/rooms/{room_id}/posts/diaries/{diary_id}",
        json={"image_ids": image_ids},
    )


def test_text_notes_require_a_paired_active_member_and_hide_private_source(posts_app):
    app, _ = posts_app
    with clients(app) as (owner, partner, stranger):
        register(owner, "note-owner", "甲")
        register(partner, "note-partner", "乙")
        register(stranger, "note-stranger", "丙")
        waiting_room = owner.post("/api/rooms").json()["id"]
        assert owner.post(
            f"/api/rooms/{waiting_room}/posts/notes", json={"body": "未配对"}
        ).status_code in {404, 409}
        invite = owner.post(f"/api/rooms/{waiting_room}/invites").json()["code"]
        assert partner.post(
            "/api/room-invites/join", json={"code": invite}
        ).status_code == 200

        created = owner.post(
            f"/api/rooms/{waiting_room}/posts/notes", json={"body": "  今天很好  "}
        )
        assert created.status_code == 201
        assert created.json()["snapshot"] == {"body": "今天很好", "type": "note"}
        assert created.json()["mine"] is True
        assert set(created.json()["author"]) == {"nickname", "avatar_url"}
        assert "source_id" not in created.json()
        UUID(created.json()["id"])

        partner_feed = partner.get(f"/api/rooms/{waiting_room}/feed")
        assert partner_feed.status_code == 200
        item = partner_feed.json()["items"][0]
        assert item["author"]["nickname"] == "甲"
        assert item["mine"] is False
        assert set(item["author"]) == {"nickname", "avatar_url"}
        assert "source_id" not in item
        assert "source_revision" not in item
        assert stranger.get(f"/api/rooms/{waiting_room}/feed").status_code == 404

        assert owner.post(f"/api/rooms/{waiting_room}/leave").status_code == 204
        assert partner.get(f"/api/rooms/{waiting_room}/feed").status_code == 404
        assert partner.post(
            f"/api/rooms/{waiting_room}/posts/notes", json={"body": "closed"}
        ).status_code == 404


def test_diary_snapshot_is_immutable_idempotent_and_replaced_without_interactions(
    posts_app,
):
    app, db_path = posts_app
    with clients(app) as (owner, partner, _):
        owner_profile = register(owner, "diary-owner", "甲")
        register(partner, "diary-partner", "乙")
        room_id = pair(owner, partner)
        diary_id, images = seed_confirmed_diary(db_path, owner_profile["id"])

        first = publish_diary(owner, room_id, diary_id, [images[1][0], images[0][0]])
        assert first.status_code == 200, first.text
        first_post = first.json()
        assert first_post["source_id"] == diary_id
        assert first_post["snapshot"]["text"] == "第一版"
        assert first_post["media_urls"] == [
            f"/api/media/{images[1][1]}",
            f"/api/media/{images[0][1]}",
        ]
        same = publish_diary(owner, room_id, diary_id, [images[1][0], images[0][0]])
        assert same.status_code == 200
        assert same.json()["id"] == first_post["id"]

        assert partner.put(
            f"/api/rooms/{room_id}/posts/{first_post['id']}/like"
        ).status_code == 200
        comment = partner.post(
            f"/api/rooms/{room_id}/posts/{first_post['id']}/comments",
            json={"client_request_id": "retry-1", "body": "真好"},
        )
        assert comment.status_code == 201

        execute(
            db_path,
            "UPDATE diaries SET text='第二版' WHERE id=?",
            (diary_id,),
        )
        unchanged = partner.get(f"/api/rooms/{room_id}/feed").json()["items"][0]
        assert unchanged["id"] == first_post["id"]
        assert unchanged["snapshot"]["text"] == "第一版"
        assert unchanged["like_count"] == 1
        assert [item["body"] for item in unchanged["comments"]] == ["真好"]

        replacement = publish_diary(owner, room_id, diary_id, [images[0][0]])
        assert replacement.status_code == 200
        replacement_post = replacement.json()
        assert replacement_post["id"] != first_post["id"]
        assert replacement_post["snapshot"]["text"] == "第二版"
        assert replacement_post["like_count"] == 0
        assert replacement_post["comments"] == []
        rows = fetch_all(
            db_path,
            "SELECT id, status, revoked_at FROM room_posts "
            "WHERE source_type='diary' ORDER BY published_at, id",
        )
        assert {row["id"]: row["status"] for row in rows} == {
            first_post["id"]: "revoked",
            replacement_post["id"]: "published",
        }
        assert next(row for row in rows if row["id"] == first_post["id"])[
            "revoked_at"
        ] is not None
        assert fetch_one(
            db_path,
            "SELECT COUNT(*) count FROM post_likes WHERE post_id=?",
            (first_post["id"],),
        )["count"] == 1
        assert fetch_one(
            db_path,
            "SELECT COUNT(*) count FROM post_comments WHERE post_id=?",
            (first_post["id"],),
        )["count"] == 1
        assert partner.get(f"/api/rooms/{room_id}/feed").json()["items"][0][
            "id"
        ] == replacement_post["id"]


def test_diary_publication_validates_owner_confirmation_kept_selection_and_asset(
    posts_app,
):
    app, db_path = posts_app
    with clients(app) as (owner, partner, _):
        owner_profile = register(owner, "validation-owner", "甲")
        partner_profile = register(partner, "validation-partner", "乙")
        room_id = pair(owner, partner)
        diary_id, images = seed_confirmed_diary(db_path, owner_profile["id"])
        foreign_diary, foreign_images = seed_confirmed_diary(
            db_path, partner_profile["id"]
        )
        execute(db_path, "UPDATE images SET kept=0 WHERE id=?", (images[1][0],))
        draft_id = execute(
            db_path,
            "INSERT INTO diaries (date, text, status, user_id) "
            "VALUES ('2026-08-04', 'draft', 'draft', ?)",
            (owner_profile["id"],),
        )

        assert publish_diary(owner, room_id, foreign_diary, []).status_code == 404
        assert publish_diary(owner, room_id, draft_id, []).status_code == 409
        assert publish_diary(owner, room_id, diary_id, [images[1][0]]).status_code == 400
        assert publish_diary(
            owner, room_id, diary_id, [foreign_images[0][0]]
        ).status_code == 400
        assert publish_diary(
            owner, room_id, diary_id, [images[0][0], images[0][0]]
        ).status_code == 400
        good = publish_diary(owner, room_id, diary_id, [images[0][0]])
        assert good.status_code == 200
        relation = fetch_one(
            db_path,
            "SELECT post_id, asset_id, ordinal FROM room_post_media WHERE post_id=?",
            (good.json()["id"],),
        )
        assert dict(relation) == {
            "post_id": good.json()["id"],
            "asset_id": images[0][1],
            "ordinal": 0,
        }


def test_diary_revision_only_change_replaces_identical_public_snapshot(posts_app):
    app, db_path = posts_app
    with clients(app) as (owner, partner, _):
        owner_profile = register(owner, "revision-diary-owner", "甲")
        register(partner, "revision-diary-partner", "乙")
        room_id = pair(owner, partner)
        diary_id, images = seed_confirmed_diary(db_path, owner_profile["id"])
        first = publish_diary(owner, room_id, diary_id, [images[0][0]]).json()
        assert partner.put(
            f"/api/rooms/{room_id}/posts/{first['id']}/like"
        ).status_code == 200

        execute(
            db_path,
            "UPDATE diaries SET source='hybrid', "
            "confirmed_at='2026-08-03T11:00:00Z' WHERE id=?",
            (diary_id,),
        )
        replacement = publish_diary(
            owner, room_id, diary_id, [images[0][0]]
        ).json()

        assert replacement["snapshot"] == first["snapshot"]
        assert replacement["id"] != first["id"]
        assert replacement["published_at"] != first["published_at"]
        assert replacement["like_count"] == 0
        assert fetch_one(
            db_path,
            "SELECT status FROM room_posts WHERE id=?",
            (first["id"],),
        )["status"] == "revoked"


def test_weekly_comic_snapshot_is_server_built_and_partner_safe(posts_app):
    app, db_path = posts_app
    with clients(app) as (owner, partner, _):
        owner_profile = register(owner, "comic-owner", "甲")
        partner_profile = register(partner, "comic-partner", "乙")
        room_id = pair(owner, partner)
        comic_id, asset_id = seed_comic(db_path, owner_profile["id"])
        foreign_comic, _ = seed_comic(db_path, partner_profile["id"], "foreign")

        assert partner.put(
            f"/api/rooms/{room_id}/posts/comics/{comic_id}"
        ).status_code == 404
        assert owner.put(
            f"/api/rooms/{room_id}/posts/comics/{foreign_comic}"
        ).status_code == 404
        published = owner.put(f"/api/rooms/{room_id}/posts/comics/{comic_id}")
        assert published.status_code == 200, published.text
        assert published.json()["snapshot"] == {
            "caption": "一周小记",
            "image_url": f"/api/media/{asset_id}",
            "style": "warm",
            "type": "weekly_comic",
            "week_end": "2026-08-02",
            "week_start": "2026-07-27",
        }
        partner_item = partner.get(f"/api/rooms/{room_id}/feed").json()["items"][0]
        assert "source_id" not in partner_item
        assert "prompt" not in json.dumps(partner_item)
        assert partner_item["media_urls"] == [f"/api/media/{asset_id}"]


def test_comic_revision_only_change_replaces_identical_public_snapshot(posts_app):
    app, db_path = posts_app
    with clients(app) as (owner, partner, _):
        owner_profile = register(owner, "revision-comic-owner", "甲")
        register(partner, "revision-comic-partner", "乙")
        room_id = pair(owner, partner)
        comic_id, _ = seed_comic(db_path, owner_profile["id"])
        first = owner.put(
            f"/api/rooms/{room_id}/posts/comics/{comic_id}"
        ).json()

        execute(
            db_path,
            "UPDATE weekly_comics SET prompt='replanned private prompt', "
            "style_prompt='new private style prompt' WHERE id=?",
            (comic_id,),
        )
        replacement = owner.put(
            f"/api/rooms/{room_id}/posts/comics/{comic_id}"
        ).json()

        assert replacement["snapshot"] == first["snapshot"]
        assert replacement["id"] != first["id"]
        assert replacement["published_at"] != first["published_at"]
        assert fetch_one(
            db_path,
            "SELECT status FROM room_posts WHERE id=?",
            (first["id"],),
        )["status"] == "revoked"


def test_like_comment_retry_soft_delete_and_withdrawal(posts_app):
    app, _ = posts_app
    with clients(app) as (owner, partner, stranger):
        register(owner, "interact-owner", "甲")
        register(partner, "interact-partner", "乙")
        register(stranger, "interact-stranger", "丙")
        room_id = pair(owner, partner)
        post = owner.post(
            f"/api/rooms/{room_id}/posts/notes", json={"body": "hello"}
        ).json()

        like_url = f"/api/rooms/{room_id}/posts/{post['id']}/like"
        assert partner.put(like_url).json() == {"like_count": 1, "liked": True}
        assert partner.put(like_url).json() == {"like_count": 1, "liked": True}
        assert partner.delete(like_url).json() == {"like_count": 0, "liked": False}
        assert partner.delete(like_url).json() == {"like_count": 0, "liked": False}
        assert stranger.put(like_url).status_code == 404

        payload = {"client_request_id": "same-request", "body": "first body"}
        first = partner.post(
            f"/api/rooms/{room_id}/posts/{post['id']}/comments", json=payload
        )
        retry = partner.post(
            f"/api/rooms/{room_id}/posts/{post['id']}/comments",
            json={"client_request_id": "same-request", "body": "changed retry"},
        )
        assert first.status_code == 201
        assert retry.status_code == 200
        assert retry.json()["id"] == first.json()["id"]
        assert retry.json()["body"] == "first body"
        assert set(first.json()["author"]) == {"nickname", "avatar_url"}
        assert owner.delete(
            f"/api/rooms/{room_id}/comments/{first.json()['id']}"
        ).status_code == 404
        assert partner.delete(
            f"/api/rooms/{room_id}/comments/{first.json()['id']}"
        ).status_code == 204
        assert partner.delete(
            f"/api/rooms/{room_id}/comments/{first.json()['id']}"
        ).status_code == 204
        assert owner.get(f"/api/rooms/{room_id}/feed").json()["items"][0][
            "comments"
        ] == []

        assert partner.delete(
            f"/api/rooms/{room_id}/posts/{post['id']}"
        ).status_code == 404
        assert owner.delete(
            f"/api/rooms/{room_id}/posts/{post['id']}"
        ).status_code == 204
        assert owner.get(f"/api/rooms/{room_id}/feed").json()["items"] == []
        assert partner.put(like_url).status_code == 404


def test_feed_limits_latest_comments_and_reports_full_active_count(posts_app):
    app, db_path = posts_app
    with clients(app) as (owner, partner, _):
        owner_profile = register(owner, "comments-owner", "甲")
        partner_profile = register(partner, "comments-partner", "乙")
        room_id = pair(owner, partner)
        post_id = owner.post(
            f"/api/rooms/{room_id}/posts/notes", json={"body": "many comments"}
        ).json()["id"]

        for index in range(55):
            author_id = (
                owner_profile["id"] if index % 2 == 0 else partner_profile["id"]
            )
            comment_id = f"00000000-0000-4000-8000-{index + 1:012d}"
            created_at = (
                "2026-08-03T12:20:00+00:00"
                if 20 <= index <= 24
                else f"2026-08-03T12:{index:02d}:00+00:00"
            )
            execute(
                db_path,
                "INSERT INTO post_comments "
                "(id, post_id, author_user_id, client_request_id, body, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (
                    comment_id,
                    post_id,
                    author_id,
                    f"request-{index:02d}",
                    f"comment-{index:02d}",
                    created_at,
                ),
            )
        execute(
            db_path,
            "INSERT INTO post_comments "
            "(id, post_id, author_user_id, client_request_id, body, created_at, deleted_at) "
            "VALUES (?, ?, ?, 'deleted-request', 'deleted', "
            "'2026-08-03T13:00:00+00:00', '2026-08-03T13:01:00+00:00')",
            (str(uuid4()), post_id, owner_profile["id"]),
        )

        item = partner.get(f"/api/rooms/{room_id}/feed").json()["items"][0]
        page_cursor = None
        paged_comments = []
        while True:
            params = {"page_size": 17}
            if page_cursor is not None:
                params["cursor"] = page_cursor
            response = partner.get(
                f"/api/rooms/{room_id}/posts/{post_id}/comments",
                params=params,
            )
            assert response.status_code == 200
            page = response.json()
            assert page["total_count"] == 55
            paged_comments.extend(page["items"])
            page_cursor = page["next_cursor"]
            if page_cursor is None:
                break

    assert item["comment_count"] == 55
    assert item["comments_truncated"] is True
    assert len(item["comments"]) == 50
    assert [comment["body"] for comment in item["comments"]] == [
        f"comment-{index:02d}" for index in range(5, 55)
    ]
    for comment in item["comments"]:
        assert set(comment["author"]) == {"nickname", "avatar_url"}
    assert [comment["body"] for comment in paged_comments] == [
        f"comment-{index:02d}" for index in range(55)
    ]
    assert len({comment["id"] for comment in paged_comments}) == 55
    assert all(
        set(comment["author"]) == {"nickname", "avatar_url"}
        for comment in paged_comments
    )


def test_comment_pagination_rejects_invalid_cursor_and_inaccessible_posts(posts_app):
    app, _ = posts_app
    with clients(app) as (owner, partner, stranger):
        register(owner, "comment-access-owner", "甲")
        register(partner, "comment-access-partner", "乙")
        register(stranger, "comment-access-stranger", "丙")
        room_id = pair(owner, partner)
        post = owner.post(
            f"/api/rooms/{room_id}/posts/notes", json={"body": "post"}
        ).json()
        created = owner.post(
            f"/api/rooms/{room_id}/posts/{post['id']}/comments",
            json={"client_request_id": "one", "body": "mine"},
        ).json()
        comments_url = f"/api/rooms/{room_id}/posts/{post['id']}/comments"

        partner_page = partner.get(comments_url)
        assert partner_page.status_code == 200
        assert partner_page.json()["items"][0]["mine"] is False
        assert owner.get(comments_url).json()["items"][0]["mine"] is True
        assert stranger.get(comments_url).status_code == 404

        noncanonical_cursor = base64.urlsafe_b64encode(
            json.dumps(
                ["2026-08-03T13:00:00+01:00", created["id"]],
                separators=(",", ":"),
            ).encode()
        ).decode().rstrip("=")
        assert partner.get(
            comments_url, params={"cursor": noncanonical_cursor}
        ).status_code == 400

        assert owner.delete(
            f"/api/rooms/{room_id}/posts/{post['id']}"
        ).status_code == 204
        assert partner.get(comments_url).status_code == 404

        active_post = owner.post(
            f"/api/rooms/{room_id}/posts/notes", json={"body": "active until leave"}
        ).json()
        active_comments_url = (
            f"/api/rooms/{room_id}/posts/{active_post['id']}/comments"
        )
        assert owner.post(f"/api/rooms/{room_id}/leave").status_code == 204
        assert partner.get(active_comments_url).status_code == 404


def test_comment_pagination_accepts_rows_created_by_database_default(posts_app):
    app, db_path = posts_app
    with clients(app) as (owner, partner, _):
        owner_profile = register(owner, "default-time-owner", "甲")
        register(partner, "default-time-partner", "乙")
        room_id = pair(owner, partner)
        post_id = owner.post(
            f"/api/rooms/{room_id}/posts/notes", json={"body": "default times"}
        ).json()["id"]
        expected_ids = []
        for index in range(3):
            comment_id = f"10000000-0000-4000-8000-{index + 1:012d}"
            expected_ids.append(comment_id)
            execute(
                db_path,
                "INSERT INTO post_comments "
                "(id, post_id, author_user_id, client_request_id, body) "
                "VALUES (?, ?, ?, ?, ?)",
                (
                    comment_id,
                    post_id,
                    owner_profile["id"],
                    f"default-{index}",
                    f"default comment {index}",
                ),
            )

        cursor = None
        collected = []
        while True:
            params = {"page_size": 1}
            if cursor is not None:
                params["cursor"] = cursor
            response = partner.get(
                f"/api/rooms/{room_id}/posts/{post_id}/comments",
                params=params,
            )
            assert response.status_code == 200
            page = response.json()
            collected.extend(comment["id"] for comment in page["items"])
            cursor = page["next_cursor"]
            if cursor is None:
                break

    assert collected == expected_ids


def test_cursor_pagination_is_stable_with_equal_times_and_interleaved_insert(posts_app):
    app, db_path = posts_app
    with clients(app) as (owner, partner, _):
        register(owner, "paging-owner", "甲")
        register(partner, "paging-partner", "乙")
        room_id = pair(owner, partner)
        created_ids = []
        for index in range(52):
            response = owner.post(
                f"/api/rooms/{room_id}/posts/notes", json={"body": f"note-{index}"}
            )
            assert response.status_code == 201
            created_ids.append(response.json()["id"])
        for index, post_id in enumerate(created_ids):
            timestamp = (
                "2026-08-03T12:00:00+00:00"
                if index < 13
                else f"2026-08-03T11:{59 - index:02d}:00+00:00"
            )
            execute(
                db_path,
                "UPDATE room_posts SET published_at=? WHERE id=?",
                (timestamp, post_id),
            )

        expected = [
            row["id"]
            for row in fetch_all(
                db_path,
                "SELECT id FROM room_posts WHERE room_id=? AND status='published' "
                "ORDER BY published_at DESC, id DESC",
                (room_id,),
            )
        ]
        first = partner.get(
            f"/api/rooms/{room_id}/feed", params={"page_size": 7}
        ).json()
        collected = [item["id"] for item in first["items"]]
        cursor = first["next_cursor"]
        inserted = owner.post(
            f"/api/rooms/{room_id}/posts/notes", json={"body": "newer-between-pages"}
        ).json()["id"]
        while cursor:
            page = partner.get(
                f"/api/rooms/{room_id}/feed",
                params={"page_size": 7, "cursor": cursor},
            )
            assert page.status_code == 200
            body = page.json()
            collected.extend(item["id"] for item in body["items"])
            cursor = body["next_cursor"]

        assert collected == expected
        assert inserted not in collected
        assert len(collected) == len(set(collected)) == 52
        latest = partner.get(
            f"/api/rooms/{room_id}/feed", params={"page_size": 50}
        ).json()["items"]
        assert len(latest) == 50
        assert latest[0]["id"] == inserted
        assert [item["id"] for item in latest[1:]] == expected[:49]

        invalid = [
            "not-base64",
            base64.urlsafe_b64encode(b"{}").decode().rstrip("="),
            base64.urlsafe_b64encode(b'["time","not-a-uuid"]')
            .decode()
            .rstrip("="),
            base64.urlsafe_b64encode(
                json.dumps(
                    ["2026-08-03T13:00:00+01:00", expected[0]],
                    separators=(",", ":"),
                ).encode()
            )
            .decode()
            .rstrip("="),
        ]
        for value in invalid:
            assert partner.get(
                f"/api/rooms/{room_id}/feed", params={"cursor": value}
            ).status_code == 400


def test_snapshot_json_and_hash_are_canonical_sha256(posts_app):
    app, db_path = posts_app
    with clients(app) as (owner, partner, _):
        register(owner, "hash-owner", "甲")
        register(partner, "hash-partner", "乙")
        room_id = pair(owner, partner)
        post = owner.post(
            f"/api/rooms/{room_id}/posts/notes", json={"body": "canonical"}
        ).json()
    row = fetch_one(
        db_path,
        "SELECT snapshot_json, snapshot_hash FROM room_posts WHERE id=?",
        (post["id"],),
    )
    expected_json = json.dumps(
        {"body": "canonical", "type": "note"},
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    assert row["snapshot_json"] == expected_json
    assert row["snapshot_hash"] == hashlib.sha256(expected_json.encode()).hexdigest()


def test_legacy_media_import_and_post_link_roll_back_as_one_unit(posts_app):
    app, db_path = posts_app
    import config

    upload_dir = Path(config.get_upload_dir())
    upload_dir.mkdir(parents=True, exist_ok=True)
    legacy_path = upload_dir / "legacy-diary.png"
    legacy_path.write_bytes(PNG_BYTES)

    with clients(app) as (owner, partner, _):
        owner_profile = register(owner, "atomic-owner", "甲")
        register(partner, "atomic-partner", "乙")
        room_id = pair(owner, partner)
        diary_id, _ = seed_confirmed_diary(
            db_path, owner_profile["id"], image_count=0
        )
        image_id = execute(
            db_path,
            "INSERT INTO images (diary_id, url, kept) VALUES (?, ?, 1)",
            (diary_id, "/api/upload/legacy-diary.png"),
        )
        execute(
            db_path,
            "CREATE TRIGGER reject_room_post_media BEFORE INSERT ON room_post_media "
            "BEGIN SELECT RAISE(ABORT, 'forced relation failure'); END",
        )

        with TestClient(
            app,
            base_url="http://testserver",
            raise_server_exceptions=False,
        ) as resilient_owner:
            login = resilient_owner.post(
                "/api/auth/login",
                json={"username": "atomic-owner", "password": PASSWORD},
            )
            assert login.status_code == 200
            failed = publish_diary(
                resilient_owner, room_id, diary_id, [image_id]
            )
            assert failed.status_code == 500

    assert fetch_one(
        db_path,
        "SELECT COUNT(*) count FROM room_posts WHERE room_id=?",
        (room_id,),
    )["count"] == 0
    assert fetch_one(
        db_path,
        "SELECT COUNT(*) count FROM media_assets WHERE owner_user_id=?",
        (owner_profile["id"],),
    )["count"] == 0
    assert sorted(path.name for path in upload_dir.iterdir()) == ["legacy-diary.png"]
