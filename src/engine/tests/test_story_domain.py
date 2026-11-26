import importlib
import sqlite3
from contextlib import contextmanager

import pytest
from fastapi.testclient import TestClient


PASSWORD = "correct horse battery"
RECORD_DATE = "2026-08-03"
FOREIGN_ORIGIN = "https://attacker.example"
PNG_BYTES = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01"
    b"\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15\xc4\x89"
)


def story_app(tmp_path, monkeypatch):
    monkeypatch.setenv("ZHIJI_DB_PATH", str(tmp_path / "story.sqlite3"))
    monkeypatch.setenv("ZHIJI_UPLOAD_DIR", str(tmp_path / "uploads"))
    monkeypatch.setenv("FRONTEND_ORIGINS", "http://localhost:5173")
    monkeypatch.setenv("SESSION_COOKIE_SECURE", "false")

    import config
    import database
    import main

    importlib.reload(config)
    importlib.reload(database)
    return importlib.reload(main).app


@contextmanager
def accounts(app):
    with TestClient(app, base_url="http://testserver") as alice, TestClient(
        app, base_url="http://testserver"
    ) as bob:
        alice_profile = alice.post(
            "/api/auth/register",
            json={
                "username": "story-alice",
                "password": PASSWORD,
                "nickname": "Alice",
            },
        )
        bob_profile = bob.post(
            "/api/auth/register",
            json={
                "username": "story-bob",
                "password": PASSWORD,
                "nickname": "Bob",
            },
        )
        assert alice_profile.status_code == bob_profile.status_code == 201
        yield alice, bob, alice_profile.json(), bob_profile.json()


@contextmanager
def three_accounts(app):
    with TestClient(app, base_url="http://testserver") as alice, TestClient(
        app, base_url="http://testserver"
    ) as bob, TestClient(app, base_url="http://testserver") as carol:
        alice_profile = alice.post(
            "/api/auth/register",
            json={
                "username": "story-three-alice",
                "password": PASSWORD,
                "nickname": "Alice",
            },
        )
        bob_profile = bob.post(
            "/api/auth/register",
            json={
                "username": "story-three-bob",
                "password": PASSWORD,
                "nickname": "Bob",
            },
        )
        carol_profile = carol.post(
            "/api/auth/register",
            json={
                "username": "story-three-carol",
                "password": PASSWORD,
                "nickname": "Carol",
            },
        )
        assert (
            alice_profile.status_code
            == bob_profile.status_code
            == carol_profile.status_code
            == 201
        )
        yield (
            alice,
            bob,
            carol,
            alice_profile.json(),
            bob_profile.json(),
            carol_profile.json(),
        )


def confirmed_diary(client, text="早上买了热豆浆，傍晚看到很低的云。"):
    diary = client.post("/api/diary", json={"date": RECORD_DATE})
    assert diary.status_code == 200
    updated = client.put(
        f"/api/diary/{diary.json()['id']}",
        json={"text": text, "status": "confirmed", "source": "manual"},
    )
    assert updated.status_code == 200
    return updated.json()


def execute(db_path, sql, params=()):
    with sqlite3.connect(db_path) as db:
        db.execute(sql, params)
        db.commit()


def fetch_all(db_path, sql, params=()):
    with sqlite3.connect(db_path) as db:
        db.row_factory = sqlite3.Row
        return [dict(row) for row in db.execute(sql, params).fetchall()]


def upload_png(client, filename="source.png"):
    response = client.post(
        "/api/upload",
        files={"file": (filename, PNG_BYTES, "image/png")},
    )
    assert response.status_code == 200, response.text
    return response.json()


def join_subscription(owner, subscriber):
    invite = owner.post("/api/subscription-invites").json()
    joined = subscriber.post("/api/subscription-invites/join", json={"code": invite["code"]})
    assert joined.status_code == 201, joined.text
    return joined.json()


@pytest.mark.asyncio
async def test_story_domain_tables_exist(db):
    cursor = await db.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name IN "
        "('character_profiles', 'story_works', 'work_assets', "
        "'subscriptions', 'subscription_invites', 'publications', 'responses', "
        "'work_audience', 'work_responses')"
    )
    assert {row["name"] for row in await cursor.fetchall()} == {
        "character_profiles",
        "story_works",
        "work_assets",
        "subscriptions",
        "subscription_invites",
        "publications",
        "responses",
        "work_audience",
        "work_responses",
    }


def test_story_work_is_owned_and_can_be_shared_to_a_subscriber_space(
    tmp_path, monkeypatch
):
    app = story_app(tmp_path, monkeypatch)
    with accounts(app) as (alice, bob, alice_profile, bob_profile):
        diary = confirmed_diary(alice)

        created = alice.post(
            "/api/story/works",
            json={
                "source_diary_id": diary["id"],
                "selected_segments": ["早上买了热豆浆"],
                "medium": "picture_book",
                "narrative_mode": "true_record",
                "style": "watercolor",
                "forbidden_content": "不要出现公司名",
                "title": "热豆浆这一页",
            },
        )

        assert created.status_code == 201, created.text
        work = created.json()
        assert work["owner_user_id"] == alice_profile["id"]
        assert work["source_diary_id"] == diary["id"]
        assert work["medium"] == "picture_book"
        assert work["status"] == "ready"
        assert work["assets"][0]["asset_type"] == "text"
        assert "早上买了热豆浆" in work["assets"][0]["text"]

        assert bob.get("/api/story/works").json() == []
        blocked = bob.post(
            "/api/story/works",
            json={
                "source_diary_id": diary["id"],
                "selected_segments": ["偷看"],
                "medium": "comic",
                "narrative_mode": "true_record",
                "style": "pixel",
            },
        )
        assert blocked.status_code == 404

        invite = alice.post("/api/subscription-invites").json()
        joined = bob.post("/api/subscription-invites/join", json={"code": invite["code"]})
        assert joined.status_code == 201, joined.text
        subscription = joined.json()
        assert subscription["owner"]["id"] == alice_profile["id"]
        assert subscription["subscriber"]["id"] == bob_profile["id"]

        initial_audience = alice.get(f"/api/story/works/{work['id']}/audience")
        assert initial_audience.status_code == 200
        assert initial_audience.json()["items"][0]["selected"] is False

        saved = alice.put(
            f"/api/story/works/{work['id']}/publication",
            json={"subscription_ids": [subscription["id"]]},
        )
        assert saved.status_code == 200, saved.text
        saved_item = saved.json()["audience"]["items"][0]
        assert saved_item["subscription_id"] == subscription["id"]
        assert saved_item["selected"] is True
        first_granted_at = saved_item["granted_at"]

        same = alice.put(
            f"/api/story/works/{work['id']}/audience",
            json={"subscription_ids": [subscription["id"]]},
        )
        assert same.status_code == 200
        assert same.json()["items"][0]["granted_at"] == first_granted_at

        feed = bob.get("/api/story/feed")
        assert feed.status_code == 200
        assert feed.json()["items"][0]["id"] == work["id"]
        assert feed.json()["items"][0]["title"] == "热豆浆这一页"
        assert feed.json()["items"][0]["owner"]["id"] == alice_profile["id"]


def test_audience_replacement_and_relationship_exit_revoke_access(
    tmp_path, monkeypatch
):
    app = story_app(tmp_path, monkeypatch)
    db_path = tmp_path / "story.sqlite3"
    with three_accounts(app) as (
        alice,
        bob,
        carol,
        alice_profile,
        bob_profile,
        carol_profile,
    ):
        diary = confirmed_diary(alice)
        work = alice.post(
            "/api/story/works",
            json={
                "source_diary_id": diary["id"],
                "selected_segments": ["早上买了热豆浆"],
                "medium": "picture_book",
                "narrative_mode": "true_record",
                "style": "watercolor",
            },
        ).json()
        bob_subscription = join_subscription(alice, bob)
        carol_subscription = join_subscription(alice, carol)

        blocked = bob.put(
            f"/api/story/works/{work['id']}/publication",
            json={"subscription_ids": [bob_subscription["id"]]},
        )
        foreign_origin = alice.put(
            f"/api/story/works/{work['id']}/publication",
            json={"subscription_ids": [bob_subscription["id"]]},
            headers={"Origin": FOREIGN_ORIGIN},
        )
        many = alice.put(
            f"/api/story/works/{work['id']}/publication",
            json={
                "subscription_ids": [
                    bob_subscription["id"],
                    carol_subscription["id"],
                ]
            },
        )
        selected_ids = {
            item["subscription_id"]
            for item in many.json()["audience"]["items"]
            if item["selected"]
        }
        bob_response = bob.put(f"/api/story/works/{work['id']}/like")
        revoked = alice.put(
            f"/api/story/works/{work['id']}/audience",
            json={"subscription_ids": [carol_subscription["id"]]},
        )
        delete_cross_site = bob.delete(
            f"/api/subscriptions/{carol_subscription['id']}",
            headers={"Origin": FOREIGN_ORIGIN},
        )
        left = bob.delete(f"/api/subscriptions/{bob_subscription['id']}")
        rejoined = join_subscription(alice, bob)

    assert blocked.status_code == 404
    assert foreign_origin.status_code == 403
    assert many.status_code == 200, many.text
    assert selected_ids == {bob_subscription["id"], carol_subscription["id"]}
    assert bob_response.status_code == 200
    assert revoked.status_code == 200
    assert {
        item["subscription_id"]
        for item in revoked.json()["items"]
        if item["selected"]
    } == {carol_subscription["id"]}
    assert delete_cross_site.status_code == 403
    assert left.status_code == 204
    assert rejoined["id"] == bob_subscription["id"]
    assert rejoined["status"] == "active"

    audience_rows = fetch_all(
        db_path,
        "SELECT subscription_id, status FROM work_audience ORDER BY subscription_id",
    )
    assert audience_rows == [
        {"subscription_id": bob_subscription["id"], "status": "revoked"},
        {"subscription_id": carol_subscription["id"], "status": "active"},
    ]
    like_rows = fetch_all(
        db_path,
        "SELECT viewer_user_id, deleted_at FROM work_likes",
    )
    assert like_rows[0]["viewer_user_id"] == bob_profile["id"]
    assert like_rows[0]["deleted_at"] is not None
    assert bob.get("/api/story/feed").json()["items"] == []
    assert carol.get("/api/story/feed").json()["items"][0]["id"] == work["id"]


def test_legacy_response_and_publication_routes_are_retired(
    tmp_path, monkeypatch
):
    """The single-overwritable work_responses flow and the legacy publications
    API are gone; work_responses survives only as a read-only history table."""
    app = story_app(tmp_path, monkeypatch)
    db_path = tmp_path / "story.sqlite3"
    with three_accounts(app) as (
        alice,
        bob,
        carol,
        _alice_profile,
        bob_profile,
        _carol_profile,
    ):
        diary = confirmed_diary(alice)
        work = alice.post(
            "/api/story/works",
            json={
                "source_diary_id": diary["id"],
                "selected_segments": ["早上买了热豆浆"],
                "medium": "picture_book",
                "narrative_mode": "true_record",
                "style": "watercolor",
            },
        ).json()
        subscription = join_subscription(alice, bob)
        grant = alice.put(
            f"/api/story/works/{work['id']}/publication",
            json={"subscription_ids": [subscription["id"]]},
        )
        assert grant.status_code == 200

        retired_response = bob.put(
            f"/api/story/works/{work['id']}/response",
            json={"seen": True, "body_kind": "text", "body": "我看见啦"},
        )
        retired_list = alice.get(f"/api/story/works/{work['id']}/responses")
        legacy_publish = alice.post(f"/api/story/works/{work['id']}/publications")
        legacy_feed = bob.get("/api/publications/feed")
        legacy_create_response = bob.post(
            "/api/publications/legacy/responses",
            json={"kind": "text", "body": "旧回应"},
        )
        legacy_list_response = alice.get("/api/publications/legacy/responses")

    assert retired_response.status_code == 404
    assert retired_list.status_code == 404
    assert legacy_publish.status_code == 404
    assert legacy_feed.status_code == 404
    assert legacy_create_response.status_code == 404
    assert legacy_list_response.status_code == 404
    # no production writes to the retired tables
    assert fetch_all(db_path, "SELECT COUNT(*) AS count FROM work_responses")[0]["count"] == 0
    assert fetch_all(db_path, "SELECT COUNT(*) AS count FROM responses")[0]["count"] == 0
    assert fetch_all(db_path, "SELECT COUNT(*) AS count FROM publications")[0]["count"] == 0


def test_story_feed_cursor_order_and_revocation(tmp_path, monkeypatch):
    app = story_app(tmp_path, monkeypatch)
    with three_accounts(app) as (
        alice,
        bob,
        carol,
        _alice_profile,
        _bob_profile,
        _carol_profile,
    ):
        alice_work = alice.post(
            "/api/story/works",
            json={
                "source_diary_id": confirmed_diary(alice)["id"],
                "selected_segments": ["Alice 的早晨"],
                "medium": "picture_book",
                "narrative_mode": "true_record",
                "style": "watercolor",
            },
        ).json()
        carol_work = carol.post(
            "/api/story/works",
            json={
                "source_diary_id": confirmed_diary(carol)["id"],
                "selected_segments": ["Carol 的夜晚"],
                "medium": "picture_book",
                "narrative_mode": "true_record",
                "style": "pixel",
            },
        ).json()
        alice_subscription = join_subscription(alice, bob)
        carol_subscription = join_subscription(carol, bob)
        assert alice.put(
            f"/api/story/works/{alice_work['id']}/publication",
            json={"subscription_ids": [alice_subscription["id"]]},
        ).status_code == 200
        assert carol.put(
            f"/api/story/works/{carol_work['id']}/publication",
            json={"subscription_ids": [carol_subscription["id"]]},
        ).status_code == 200

        first_page = bob.get("/api/story/feed?page_size=1")
        next_cursor = first_page.json()["next_cursor"]
        second_page = bob.get(f"/api/story/feed?page_size=1&cursor={next_cursor}")
        malformed = bob.get("/api/story/feed?cursor=not-a-real-cursor")
        assert carol.put(
            f"/api/story/works/{carol_work['id']}/audience",
            json={"subscription_ids": []},
        ).status_code == 200
        after_revoke = bob.get("/api/story/feed")

    assert first_page.status_code == 200
    assert len(first_page.json()["items"]) == 1
    assert next_cursor
    assert second_page.status_code == 200
    assert len(second_page.json()["items"]) == 1
    assert first_page.json()["items"][0]["id"] != second_page.json()["items"][0]["id"]
    assert second_page.json()["next_cursor"] is None
    assert malformed.status_code == 400
    assert {item["id"] for item in after_revoke.json()["items"]} == {alice_work["id"]}


def test_story_work_saves_selected_source_media(tmp_path, monkeypatch):
    app = story_app(tmp_path, monkeypatch)
    db_path = tmp_path / "story.sqlite3"
    with accounts(app) as (alice, bob, alice_profile, bob_profile):
        diary = confirmed_diary(alice, "午休绕远了一点，路边的树影很密。")
        fragment_asset = upload_png(alice, "fragment.png")
        diary_asset = upload_png(alice, "diary.png")
        fragment = alice.post(
            "/api/fragments",
            json={
                "date": RECORD_DATE,
                "content": "午休绕远了一点",
                "photo_url": fragment_asset["url"],
                "photo_asset_id": fragment_asset["asset_id"],
            },
        ).json()
        execute(
            db_path,
            "INSERT INTO images "
            "(diary_id, style, url, kept, asset_id) VALUES (?, 'watercolor', ?, 1, ?)",
            (diary["id"], diary_asset["url"], diary_asset["asset_id"]),
        )

        response = alice.post(
            "/api/story/works",
            json={
                "source_diary_id": diary["id"],
                "selected_segments": ["午休绕远了一点"],
                "source_fragment_ids": [fragment["id"]],
                "source_image_asset_ids": [diary_asset["asset_id"]],
                "source_weekly_comic_ids": [],
                "medium": "picture_book",
                "narrative_mode": "true_record",
                "style": "watercolor",
            },
        )
        foreign = alice.post(
            "/api/story/works",
            json={
                "source_diary_id": diary["id"],
                "selected_segments": ["偷看"],
                "source_fragment_ids": [
                    bob.post(
                        "/api/fragments",
                        json={"date": RECORD_DATE, "content": "Bob 私有"},
                    ).json()["id"]
                ],
                "medium": "picture_book",
                "narrative_mode": "true_record",
                "style": "watercolor",
            },
        )

    assert response.status_code == 201, response.text
    work = response.json()
    assert work["status"] == "ready"
    assert [asset["asset_type"] for asset in work["assets"]] == [
        "text",
        "image",
        "image",
    ]
    assert [asset["asset_id"] for asset in work["assets"][1:]] == [
        fragment_asset["asset_id"],
        diary_asset["asset_id"],
    ]
    assert foreign.status_code == 404
    assert fetch_all(
        db_path,
        "SELECT COUNT(*) AS count FROM story_works WHERE title='偷看'",
    )[0]["count"] == 0


def test_story_work_rejects_cross_date_and_foreign_sources(tmp_path, monkeypatch):
    app = story_app(tmp_path, monkeypatch)
    db_path = tmp_path / "story.sqlite3"
    with accounts(app) as (alice, bob, alice_profile, bob_profile):
        diary = confirmed_diary(alice, "今天只记录这一天。")
        other_day_fragment = alice.post(
            "/api/fragments",
            json={"date": "2026-08-04", "content": "另一天的照片"},
        ).json()
        bob_image = upload_png(bob, "bob-diary.png")
        bob_diary = confirmed_diary(bob, "Bob 的一天")
        execute(
            db_path,
            "INSERT INTO images "
            "(diary_id, style, url, kept, asset_id) VALUES (?, 'watercolor', ?, 1, ?)",
            (bob_diary["id"], bob_image["url"], bob_image["asset_id"]),
        )
        bob_weekly = upload_png(bob, "bob-weekly.png")
        execute(
            db_path,
            "INSERT INTO weekly_comics "
            "(user_id, week_start, week_end, url, asset_id) "
            "VALUES (?, '2026-08-03', '2026-08-09', ?, ?)",
            (bob_profile["id"], bob_weekly["url"], bob_weekly["asset_id"]),
        )
        bob_comic_id = fetch_all(
            db_path,
            "SELECT id FROM weekly_comics WHERE user_id = ?",
            (bob_profile["id"],),
        )[0]["id"]

        wrong_date = alice.post(
            "/api/story/works",
            json={
                "source_diary_id": diary["id"],
                "source_fragment_ids": [other_day_fragment["id"]],
                "selected_segments": ["另一天"],
                "medium": "picture_book",
                "narrative_mode": "true_record",
                "style": "watercolor",
            },
        )
        no_diary_fragment = alice.post(
            "/api/story/works",
            json={
                "source_diary_id": None,
                "source_fragment_ids": [other_day_fragment["id"]],
                "selected_segments": ["没有日记"],
                "medium": "picture_book",
                "narrative_mode": "true_record",
                "style": "watercolor",
            },
        )
        foreign_image = alice.post(
            "/api/story/works",
            json={
                "source_diary_id": diary["id"],
                "source_image_asset_ids": [bob_image["asset_id"]],
                "selected_segments": ["别人的图"],
                "medium": "picture_book",
                "narrative_mode": "true_record",
                "style": "watercolor",
            },
        )
        foreign_weekly = alice.post(
            "/api/story/works",
            json={
                "source_diary_id": None,
                "source_weekly_comic_ids": [bob_comic_id],
                "selected_segments": ["别人的周图"],
                "medium": "weekly",
                "narrative_mode": "true_record",
                "style": "weekly",
            },
        )

    assert wrong_date.status_code == 404
    assert no_diary_fragment.status_code == 404
    assert foreign_image.status_code == 404
    assert foreign_weekly.status_code == 404
    assert fetch_all(
        db_path,
        "SELECT COUNT(*) AS count FROM story_works",
    )[0]["count"] == 0


def test_weekly_story_work_saves_comic_source_without_diary(tmp_path, monkeypatch):
    app = story_app(tmp_path, monkeypatch)
    db_path = tmp_path / "story.sqlite3"
    with accounts(app) as (alice, _bob, _alice_profile, _bob_profile):
        weekly_asset = upload_png(alice, "weekly.png")
        execute(
            db_path,
            "INSERT INTO weekly_comics "
            "(user_id, week_start, week_end, style, prompt, url, caption, asset_id) "
            "VALUES (?, '2026-08-03', '2026-08-09', 'weekly', 'prompt', ?, "
            "'这一周的图', ?)",
            (_alice_profile["id"], weekly_asset["url"], weekly_asset["asset_id"]),
        )
        comic_id = fetch_all(db_path, "SELECT id FROM weekly_comics")[0]["id"]

        response = alice.post(
            "/api/story/works",
            json={
                "source_diary_id": None,
                "selected_segments": ["这一周的图"],
                "source_weekly_comic_ids": [comic_id],
                "medium": "weekly",
                "narrative_mode": "true_record",
                "style": "weekly",
            },
        )

    assert response.status_code == 201, response.text
    work = response.json()
    assert work["status"] == "ready"
    assert [asset["asset_type"] for asset in work["assets"]] == ["text", "image"]
    assert work["assets"][1]["asset_id"] == weekly_asset["asset_id"]


def test_source_asset_legacy_failures_are_transactional(tmp_path, monkeypatch):
    app = story_app(tmp_path, monkeypatch)
    db_path = tmp_path / "story.sqlite3"
    upload_dir = tmp_path / "uploads"
    with accounts(app) as (alice, _bob, alice_profile, _bob_profile):
        diary = confirmed_diary(alice)
        execute(
            db_path,
            "INSERT INTO fragments (date, content, photo_url, user_id) "
            "VALUES (?, 'missing photo', '/api/upload/missing.png', ?)",
            (RECORD_DATE, alice_profile["id"]),
        )
        missing_fragment_id = fetch_all(
            db_path, "SELECT id FROM fragments WHERE content='missing photo'"
        )[0]["id"]

        missing = alice.post(
            "/api/story/works",
            json={
                "source_diary_id": diary["id"],
                "selected_segments": ["missing photo"],
                "source_fragment_ids": [missing_fragment_id],
                "medium": "picture_book",
                "narrative_mode": "true_record",
                "style": "watercolor",
            },
        )

        upload_dir.mkdir(parents=True, exist_ok=True)
        legacy_path = upload_dir / "legacy-fragment.png"
        legacy_path.write_bytes(PNG_BYTES)
        execute(
            db_path,
            "INSERT INTO fragments (date, content, photo_url, user_id) "
            "VALUES (?, 'legacy photo', '/api/upload/legacy-fragment.png', ?)",
            (RECORD_DATE, alice_profile["id"]),
        )
        legacy_fragment_id = fetch_all(
            db_path, "SELECT id FROM fragments WHERE content='legacy photo'"
        )[0]["id"]
        execute(
            db_path,
            "CREATE TRIGGER fail_story_work_insert BEFORE INSERT ON story_works "
            "BEGIN SELECT RAISE(ABORT, 'forced work insert failure'); END",
        )
        with TestClient(
            app,
            base_url="http://testserver",
            raise_server_exceptions=False,
        ) as non_raising_alice:
            non_raising_alice.cookies.update(alice.cookies)
            rollback = non_raising_alice.post(
                "/api/story/works",
                json={
                    "source_diary_id": diary["id"],
                    "selected_segments": ["legacy photo"],
                    "source_fragment_ids": [legacy_fragment_id],
                    "medium": "picture_book",
                    "narrative_mode": "true_record",
                    "style": "watercolor",
                },
            )

    assert missing.status_code == 409
    assert rollback.status_code == 500
    assert legacy_path.is_file()
    assert fetch_all(db_path, "SELECT id FROM story_works") == []
    assert fetch_all(db_path, "SELECT id FROM media_assets") == []
    assert sorted(path.name for path in upload_dir.iterdir()) == ["legacy-fragment.png"]


def test_character_profile_defaults_to_current_user_and_ignores_user_id_params(
    tmp_path, monkeypatch
):
    app = story_app(tmp_path, monkeypatch)
    with accounts(app) as (alice, bob, alice_profile, bob_profile):
        updated = alice.put(
            "/api/character-profile",
            params={"user_id": bob_profile["id"]},
            json={
                "source_photo_url": "/api/upload/alice.png",
                "reference_image_url": "/api/upload/alice-ref.png",
                "character_description": "短发，常背帆布包，像手账里的主角",
            },
        )
        assert updated.status_code == 200
        assert updated.json()["user_id"] == alice_profile["id"]
        assert updated.json()["version"] == 1

        assert bob.get("/api/character-profile").json()["character_description"] == ""
        assert alice.get(
            "/api/character-profile", params={"user_id": bob_profile["id"]}
        ).json()["character_description"] == "短发，常背帆布包，像手账里的主角"


def test_story_mutations_reject_foreign_origin(tmp_path, monkeypatch):
    app = story_app(tmp_path, monkeypatch)
    with TestClient(app, base_url="http://testserver") as client:
        assert client.post(
            "/api/auth/register",
            json={
                "username": "story-origin",
                "password": PASSWORD,
                "nickname": "Origin",
            },
        ).status_code == 201
        response = client.post(
            "/api/subscription-invites",
            headers={"Origin": FOREIGN_ORIGIN},
        )

    assert response.status_code == 403


def test_diary_prompt_defaults_to_self_not_family():
    import agents.diary_agent as diary_agent

    prompt = diary_agent.build_diary_prompt(
        text="今天有点累，但下班路上的风很好",
        fragments=[],
        allow_imaginative=False,
    )

    assert "让用户看到自己的日常变成连贯的叙事" in prompt
    assert "家人" not in prompt
    assert "远方挂念" not in prompt


def test_diary_ai_fill_maps_two_modes_and_allows_text_only(tmp_path, monkeypatch):
    app = story_app(tmp_path, monkeypatch)

    import routers.diary as diary_router

    calls = []

    async def fake_generate_diary(**kwargs):
        calls.append(kwargs)
        return "generated diary"

    monkeypatch.setattr(diary_router, "generate_diary", fake_generate_diary)

    with accounts(app) as (alice, bob, _alice_profile, _bob_profile):
        alice_diary = alice.post(
            "/api/diary", json={"date": RECORD_DATE}
        ).json()
        assert alice.put(
            f"/api/diary/{alice_diary['id']}",
            json={"text": "Alice text", "draft_text": "Alice current draft"},
        ).status_code == 200
        real_response = alice.post(
            f"/api/diary/{alice_diary['id']}/ai-fill",
            json={},
        )

        bob_diary = bob.post("/api/diary", json={"date": RECORD_DATE}).json()
        assert bob.put(
            f"/api/diary/{bob_diary['id']}",
            json={"text": "Bob current text"},
        ).status_code == 200
        imagery_response = bob.post(
            f"/api/diary/{bob_diary['id']}/ai-fill",
            json={"emotion_mode": "imagery"},
        )
        invalid_response = bob.post(
            f"/api/diary/{bob_diary['id']}/ai-fill",
            json={"emotion_mode": "poetic"},
        )

    assert real_response.status_code == 200
    assert real_response.json()["emotion_mode"] == "real"
    assert imagery_response.status_code == 200
    assert imagery_response.json()["emotion_mode"] == "imagery"
    assert invalid_response.status_code == 422
    assert len(calls) == 2
    assert calls[0] == {
        "text": "Alice current draft",
        "fragments": [],
        "allow_imaginative": False,
    }
    assert calls[1] == {
        "text": "Bob current text",
        "fragments": [],
        "allow_imaginative": True,
    }
    assert set(diary_router.AiFillRequest.model_fields) == {
        "emotion_mode",
        "schedule_ids",
        "fragment_ids",
    }


def test_diary_ai_fill_source_selection_is_private_and_date_bound(
    tmp_path, monkeypatch
):
    app = story_app(tmp_path, monkeypatch)

    import routers.diary as diary_router

    calls = []

    async def fake_generate_diary(**kwargs):
        calls.append(kwargs)
        return "generated diary"

    monkeypatch.setattr(diary_router, "generate_diary", fake_generate_diary)

    with accounts(app) as (alice, bob, _alice_profile, _bob_profile):
        alice_plan = alice.post(
            "/api/schedules",
            json={"date": RECORD_DATE, "title": "晚上买菜"},
        ).json()
        alice_wrong_date = alice.post(
            "/api/schedules",
            json={"date": "2026-08-04", "title": "明天的安排"},
        ).json()
        alice_fragment = alice.post(
            "/api/fragments",
            json={"date": RECORD_DATE, "content": "路边的云很低"},
        ).json()
        alice_other_fragment = alice.post(
            "/api/fragments",
            json={"date": RECORD_DATE, "content": "晚饭有番茄"},
        ).json()
        alice_wrong_date_fragment = alice.post(
            "/api/fragments",
            json={"date": "2026-08-04", "content": "错日期随记"},
        ).json()
        bob_schedule = bob.post(
            "/api/schedules",
            json={"date": RECORD_DATE, "title": "Bob 私有日程"},
        ).json()
        bob_fragment = bob.post(
            "/api/fragments",
            json={"date": RECORD_DATE, "content": "Bob 私有随记"},
        ).json()
        diary = alice.post("/api/diary", json={"date": RECORD_DATE}).json()

        empty_selection = alice.post(
            f"/api/diary/{diary['id']}/ai-fill",
            json={"emotion_mode": "real", "schedule_ids": [], "fragment_ids": []},
        )
        schedule_only = alice.post(
            f"/api/diary/{diary['id']}/ai-fill",
            json={
                "emotion_mode": "real",
                "schedule_ids": [alice_plan["id"]],
                "fragment_ids": [],
            },
        )
        default_response = alice.post(
            f"/api/diary/{diary['id']}/ai-fill",
            json={"emotion_mode": "real"},
        )
        fragment_only = alice.post(
            f"/api/diary/{diary['id']}/ai-fill",
            json={
                "emotion_mode": "real",
                "schedule_ids": [],
                "fragment_ids": [alice_fragment["id"]],
            },
        )
        foreign_schedule = alice.post(
            f"/api/diary/{diary['id']}/ai-fill",
            json={"emotion_mode": "real", "schedule_ids": [bob_schedule["id"]]},
        )
        foreign_fragment = alice.post(
            f"/api/diary/{diary['id']}/ai-fill",
            json={"emotion_mode": "real", "fragment_ids": [bob_fragment["id"]]},
        )
        wrong_date_schedule = alice.post(
            f"/api/diary/{diary['id']}/ai-fill",
            json={
                "emotion_mode": "real",
                "schedule_ids": [alice_wrong_date["id"]],
            },
        )
        wrong_date_fragment = alice.post(
            f"/api/diary/{diary['id']}/ai-fill",
            json={
                "emotion_mode": "real",
                "fragment_ids": [alice_wrong_date_fragment["id"]],
            },
        )
        too_many_sources = alice.post(
            f"/api/diary/{diary['id']}/ai-fill",
            json={"emotion_mode": "real", "schedule_ids": list(range(1, 52))},
        )
        too_many_fragments = alice.post(
            f"/api/diary/{diary['id']}/ai-fill",
            json={"emotion_mode": "real", "fragment_ids": list(range(1, 52))},
        )

    assert default_response.status_code == 200
    assert fragment_only.status_code == 200
    assert schedule_only.status_code == 400
    assert empty_selection.status_code == 400
    assert foreign_schedule.status_code == wrong_date_schedule.status_code == 200
    assert foreign_fragment.status_code == wrong_date_fragment.status_code == 404
    assert too_many_sources.status_code == 422
    assert too_many_fragments.status_code == 422
    assert {
        foreign_fragment.json()["detail"],
        wrong_date_fragment.json()["detail"],
    } == {"source records not found"}

    assert len(calls) == 4
    assert [item["id"] for item in calls[0]["fragments"]] == [
        alice_fragment["id"],
        alice_other_fragment["id"],
    ]
    assert calls[0]["text"] == ""
    assert calls[0]["allow_imaginative"] is False
    assert [item["id"] for item in calls[1]["fragments"]] == [alice_fragment["id"]]
    assert [item["id"] for item in calls[2]["fragments"]] == [
        alice_fragment["id"],
        alice_other_fragment["id"],
    ]
    assert [item["id"] for item in calls[3]["fragments"]] == [
        alice_fragment["id"],
        alice_other_fragment["id"],
    ]
    assert all(set(call) == {"text", "fragments", "allow_imaginative"} for call in calls)


def test_diary_ai_fill_rejects_mood_only_fragments(tmp_path, monkeypatch):
    app = story_app(tmp_path, monkeypatch)
    db_path = tmp_path / "story.sqlite3"

    import routers.diary as diary_router

    calls = []

    async def fake_generate_diary(**kwargs):
        calls.append(kwargs)
        return "generated diary"

    monkeypatch.setattr(diary_router, "generate_diary", fake_generate_diary)

    with accounts(app) as (alice, bob, alice_profile, bob_profile):
        execute(
            db_path,
            "INSERT INTO fragments (date, mood_tag, user_id) VALUES (?, ?, ?)",
            (RECORD_DATE, "平静", alice_profile["id"]),
        )
        execute(
            db_path,
            "INSERT INTO fragments (date, mood_tag, user_id) VALUES (?, ?, ?)",
            (RECORD_DATE, "低落", bob_profile["id"]),
        )
        alice_mood_id = fetch_all(
            db_path,
            "SELECT id FROM fragments WHERE user_id = ?",
            (alice_profile["id"],),
        )[0]["id"]
        bob_mood_id = fetch_all(
            db_path,
            "SELECT id FROM fragments WHERE user_id = ?",
            (bob_profile["id"],),
        )[0]["id"]
        alice_diary = alice.post(
            "/api/diary", json={"date": RECORD_DATE}
        ).json()
        bob_diary = bob.post("/api/diary", json={"date": RECORD_DATE}).json()

        default_response = alice.post(
            f"/api/diary/{alice_diary['id']}/ai-fill",
            json={"emotion_mode": "real"},
        )
        selected_response = bob.post(
            f"/api/diary/{bob_diary['id']}/ai-fill",
            json={"emotion_mode": "real", "fragment_ids": [bob_mood_id]},
        )

    assert alice_mood_id != bob_mood_id
    assert default_response.status_code == selected_response.status_code == 400
    assert default_response.json() == selected_response.json() == {
        "detail": "当天没有任何记录，无法用 AI 填充"
    }
    assert calls == []


def test_diary_ai_fill_rejects_oversized_aggregate_source(
    tmp_path, monkeypatch
):
    app = story_app(tmp_path, monkeypatch)

    import routers.diary as diary_router

    calls = []

    async def fake_generate_diary(**kwargs):
        calls.append(kwargs)
        return "generated diary"

    monkeypatch.setattr(diary_router, "generate_diary", fake_generate_diary)

    with accounts(app) as (alice, _bob, _alice_profile, _bob_profile):
        fragment = alice.post(
            "/api/fragments",
            json={
                "date": RECORD_DATE,
                "content": "随" * 5,
                "photo_description": "图" * 6,
            },
        ).json()
        diary = alice.post("/api/diary", json={"date": RECORD_DATE}).json()
        original_text = "文" * 3990
        assert alice.put(
            f"/api/diary/{diary['id']}", json={"text": original_text}
        ).status_code == 200

        response = alice.post(
            f"/api/diary/{diary['id']}/ai-fill",
            json={"emotion_mode": "real", "fragment_ids": [fragment["id"]]},
        )
        stored = alice.get("/api/diary", params={"date": RECORD_DATE})

    assert response.status_code == 400
    assert response.json() == {
        "detail": "AI 填充内容总长度不能超过 4000 字符"
    }
    assert stored.status_code == 200
    assert stored.json()["text"] == original_text
    assert calls == []


def test_diary_ai_fill_accepts_photo_description_only_fragment(
    tmp_path, monkeypatch
):
    app = story_app(tmp_path, monkeypatch)

    import routers.diary as diary_router

    calls = []

    async def fake_generate_diary(**kwargs):
        calls.append(kwargs)
        return "generated diary"

    monkeypatch.setattr(diary_router, "generate_diary", fake_generate_diary)

    with accounts(app) as (alice, _bob, _alice_profile, _bob_profile):
        uploaded = upload_png(alice, "photo-description-only.png")
        fragment = alice.post(
            "/api/fragments",
            json={
                "date": RECORD_DATE,
                "photo_url": uploaded["url"],
                "photo_asset_id": uploaded["asset_id"],
                "photo_description": "窗边放着一杯热茶",
            },
        ).json()
        diary = alice.post("/api/diary", json={"date": RECORD_DATE}).json()

        response = alice.post(
            f"/api/diary/{diary['id']}/ai-fill",
            json={"emotion_mode": "real", "fragment_ids": [fragment["id"]]},
        )

    assert response.status_code == 200
    assert len(calls) == 1
    assert calls[0]["text"] == ""
    assert len(calls[0]["fragments"]) == 1
    assert calls[0]["fragments"][0]["content"] is None
    assert (
        calls[0]["fragments"][0]["photo_description"]
        == "窗边放着一杯热茶"
    )


def test_diary_ai_fill_orders_fragments_by_record_time_ascending(
    tmp_path, monkeypatch
):
    app = story_app(tmp_path, monkeypatch)

    import routers.diary as diary_router

    calls = []

    async def fake_generate_diary(**kwargs):
        calls.append(kwargs)
        return "generated diary"

    monkeypatch.setattr(diary_router, "generate_diary", fake_generate_diary)

    with accounts(app) as (alice, _bob, _alice_profile, _bob_profile):
        evening = alice.post(
            "/api/fragments",
            json={
                "date": RECORD_DATE,
                "content": "夜里看星星",
                "record_time": "21:00",
            },
        ).json()
        morning = alice.post(
            "/api/fragments",
            json={
                "date": RECORD_DATE,
                "content": "早上吃豆浆",
                "record_time": "08:00",
            },
        ).json()
        diary = alice.post("/api/diary", json={"date": RECORD_DATE}).json()
        response = alice.post(
            f"/api/diary/{diary['id']}/ai-fill",
            json={"emotion_mode": "real"},
        )

    assert response.status_code == 200
    assert [item["content"] for item in calls[0]["fragments"]] == [
        "早上吃豆浆",
        "夜里看星星",
    ]
    assert [item["id"] for item in calls[0]["fragments"]] == [
        morning["id"],
        evening["id"],
    ]
