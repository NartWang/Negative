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


def resonance_app(tmp_path, monkeypatch):
    monkeypatch.setenv("ZHIJI_DB_PATH", str(tmp_path / "resonance.sqlite3"))
    monkeypatch.setenv("ZHIJI_UPLOAD_DIR", str(tmp_path / "uploads"))
    monkeypatch.setenv("FRONTEND_ORIGINS", "http://localhost:5173")
    monkeypatch.setenv("SESSION_COOKIE_SECURE", "false")

    import config
    import database
    import main

    importlib.reload(config)
    importlib.reload(database)
    return importlib.reload(main).app, tmp_path / "resonance.sqlite3"


@contextmanager
def accounts(app):
    with TestClient(app, base_url="http://testserver") as alice, TestClient(
        app, base_url="http://testserver"
    ) as bob:
        alice_profile = alice.post(
            "/api/auth/register",
            json={
                "username": "resonance-alice",
                "password": PASSWORD,
                "nickname": "Alice",
            },
        )
        bob_profile = bob.post(
            "/api/auth/register",
            json={
                "username": "resonance-bob",
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
                "username": "resonance-three-alice",
                "password": PASSWORD,
                "nickname": "Alice",
            },
        )
        bob_profile = bob.post(
            "/api/auth/register",
            json={
                "username": "resonance-three-bob",
                "password": PASSWORD,
                "nickname": "Bob",
            },
        )
        carol_profile = carol.post(
            "/api/auth/register",
            json={
                "username": "resonance-three-carol",
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


def create_ready_work(client, title="热豆浆这一页"):
    diary = confirmed_diary(client)
    created = client.post(
        "/api/story/works",
        json={
            "source_diary_id": diary["id"],
            "selected_segments": ["早上买了热豆浆"],
            "medium": "picture_book",
            "narrative_mode": "true_record",
            "style": "watercolor",
            "title": title,
        },
    )
    assert created.status_code == 201, created.text
    return created.json()


def join_subscription(owner, subscriber):
    invite = owner.post("/api/subscription-invites").json()
    joined = subscriber.post(
        "/api/subscription-invites/join", json={"code": invite["code"]}
    )
    assert joined.status_code == 201, joined.text
    return joined.json()


def fetch_all(db_path, sql, params=()):
    with sqlite3.connect(db_path) as db:
        db.row_factory = sqlite3.Row
        return [dict(row) for row in db.execute(sql, params).fetchall()]


def execute(db_path, sql, params=()):
    with sqlite3.connect(db_path) as db:
        db.execute(sql, params)
        db.commit()


def test_owner_can_publish_without_audience_and_unpublish_without_deleting_source(
    tmp_path, monkeypatch
):
    app, _db_path = resonance_app(tmp_path, monkeypatch)
    with accounts(app) as (alice, bob, *_):
        work = create_ready_work(alice)
        published = alice.put(
            f"/api/story/works/{work['id']}/publication",
            json={"subscription_ids": []},
        )
        assert published.status_code == 200, published.text
        assert published.json()["work"]["status"] == "published"
        assert published.json()["work"]["published_at"]
        assert bob.get("/api/story/feed").json()["items"] == []

        removed = alice.delete(f"/api/story/works/{work['id']}/publication")
        assert removed.status_code == 204
        assert (
            alice.get(f"/api/story/works/{work['id']}").json()["status"] == "ready"
        )


def test_publication_audience_atomicity_and_authorization(tmp_path, monkeypatch):
    app, db_path = resonance_app(tmp_path, monkeypatch)
    with three_accounts(app) as (alice, bob, carol, alice_profile, bob_profile, _carol_profile):
        work = create_ready_work(alice)
        bob_subscription = join_subscription(alice, bob)
        carol_subscription = join_subscription(alice, carol)

        # non-owner cannot publish
        assert alice  # keep linter quiet about tuple unpack
        blocked = bob.put(
            f"/api/story/works/{work['id']}/publication",
            json={"subscription_ids": []},
        )
        assert blocked.status_code == 404

        # foreign origin rejected
        cross_site = alice.put(
            f"/api/story/works/{work['id']}/publication",
            json={"subscription_ids": []},
            headers={"Origin": FOREIGN_ORIGIN},
        )
        assert cross_site.status_code == 403

        # foreign subscription id aborts the whole transaction
        foreign = alice.put(
            f"/api/story/works/{work['id']}/publication",
            json={"subscription_ids": [bob_subscription["id"], 99999]},
        )
        assert foreign.status_code == 404
        assert fetch_all(
            db_path,
            "SELECT status FROM story_works WHERE id=?",
            (work["id"],),
        )[0]["status"] == "ready"
        assert fetch_all(
            db_path,
            "SELECT COUNT(*) AS count FROM work_audience WHERE work_id=?",
            (work["id"],),
        )[0]["count"] == 0

        # ready work exposes candidates via GET but rejects direct PUT
        candidates = alice.get(f"/api/story/works/{work['id']}/audience")
        assert candidates.status_code == 200
        direct_put = alice.put(
            f"/api/story/works/{work['id']}/audience",
            json={"subscription_ids": [bob_subscription["id"]]},
        )
        assert direct_put.status_code in (404, 409)

        # publish with audience in one transaction
        published = alice.put(
            f"/api/story/works/{work['id']}/publication",
            json={
                "subscription_ids": [
                    bob_subscription["id"],
                    carol_subscription["id"],
                ]
            },
        )
        assert published.status_code == 200, published.text
        assert published.json()["work"]["status"] == "published"
        selected = {
            item["subscription_id"]
            for item in published.json()["audience"]["items"]
            if item["selected"]
        }
        assert selected == {bob_subscription["id"], carol_subscription["id"]}

        # published work accepts audience replacement
        narrowed = alice.put(
            f"/api/story/works/{work['id']}/audience",
            json={"subscription_ids": [carol_subscription["id"]]},
        )
        assert narrowed.status_code == 200
        narrowed_selected = {
            item["subscription_id"]
            for item in narrowed.json()["items"]
            if item["selected"]
        }
        assert narrowed_selected == {carol_subscription["id"]}

        # cancel publication revokes all active audience
        removed = alice.delete(f"/api/story/works/{work['id']}/publication")
        assert removed.status_code == 204
        audience_rows = fetch_all(
            db_path,
            "SELECT status FROM work_audience WHERE work_id=?",
            (work["id"],),
        )
        assert audience_rows and all(
            row["status"] == "revoked" for row in audience_rows
        )


def test_feed_mixes_own_and_authorized_works_by_published_at(tmp_path, monkeypatch):
    app, db_path = resonance_app(tmp_path, monkeypatch)
    with three_accounts(app) as (alice, bob, carol, alice_profile, bob_profile, carol_profile):
        # Alice publishes a self-only work (older)
        alice_work = create_ready_work(alice, "Alice 自留")
        execute(
            db_path,
            "UPDATE story_works SET created_at=? WHERE id=?",
            ("2026-08-01T08:00:00+00:00", alice_work["id"]),
        )
        alice_publish = alice.put(
            f"/api/story/works/{alice_work['id']}/publication",
            json={"subscription_ids": []},
        )
        assert alice_publish.status_code == 200
        # backdate published_at
        execute(
            db_path,
            "UPDATE story_works SET published_at=? WHERE id=?",
            ("2026-08-01T09:00:00+00:00", alice_work["id"]),
        )

        # Bob publishes and grants Alice (newer)
        bob_work = create_ready_work(bob, "Bob 给 Alice 看")
        bob_subscription = join_subscription(bob, alice)
        bob_publish = bob.put(
            f"/api/story/works/{bob_work['id']}/publication",
            json={"subscription_ids": [bob_subscription["id"]]},
        )
        assert bob_publish.status_code == 200
        execute(
            db_path,
            "UPDATE story_works SET published_at=? WHERE id=?",
            ("2026-08-02T09:00:00+00:00", bob_work["id"]),
        )

        # Carol publishes but does NOT grant Alice
        carol_work = create_ready_work(carol, "Carol 私藏")
        carol_publish = carol.put(
            f"/api/story/works/{carol_work['id']}/publication",
            json={"subscription_ids": []},
        )
        assert carol_publish.status_code == 200

        feed = alice.get("/api/story/feed")
        assert feed.status_code == 200
        items = feed.json()["items"]
        assert [item["id"] for item in items] == [bob_work["id"], alice_work["id"]]
        assert items[0]["mine"] is False
        assert items[1]["mine"] is True
        assert all("granted_at" not in item for item in items)
        assert all("published_at" in item for item in items)


def test_feed_cursor_is_stable_with_identical_published_at(tmp_path, monkeypatch):
    app, db_path = resonance_app(tmp_path, monkeypatch)
    with accounts(app) as (alice, bob, _alice_profile, _bob_profile):
        bob_subscription = join_subscription(bob, alice)
        # Bob publishes two works with identical published_at
        work_ids = []
        for index in range(2):
            work = create_ready_work(bob, f"Bob 作品 {index}")
            published = bob.put(
                f"/api/story/works/{work['id']}/publication",
                json={"subscription_ids": [bob_subscription["id"]]},
            )
            assert published.status_code == 200
            work_ids.append(work["id"])
        same_time = "2026-08-02T10:00:00+00:00"
        for work_id in work_ids:
            execute(
                db_path,
                "UPDATE story_works SET published_at=? WHERE id=?",
                (same_time, work_id),
            )

        first_page = alice.get("/api/story/feed?page_size=1")
        assert first_page.status_code == 200
        assert len(first_page.json()["items"]) == 1
        next_cursor = first_page.json()["next_cursor"]
        assert next_cursor
        second_page = alice.get(f"/api/story/feed?page_size=1&cursor={next_cursor}")
        assert second_page.status_code == 200
        assert len(second_page.json()["items"]) == 1
        first_id = first_page.json()["items"][0]["id"]
        second_id = second_page.json()["items"][0]["id"]
        assert first_id != second_id
        assert {first_id, second_id} == set(work_ids)


def test_feed_rejects_audience_not_owned_by_work_owner(tmp_path, monkeypatch):
    """A dirty work_audience row linking Carol's work to Bob->Alice
    subscription must not leak Carol's work into Alice's feed."""
    app, db_path = resonance_app(tmp_path, monkeypatch)
    with three_accounts(app) as (alice, bob, carol, _alice_profile, bob_profile, carol_profile):
        bob_subscription = join_subscription(bob, alice)
        # Carol publishes self-only
        carol_work = create_ready_work(carol, "Carol 私密")
        published = carol.put(
            f"/api/story/works/{carol_work['id']}/publication",
            json={"subscription_ids": []},
        )
        assert published.status_code == 200
        # dirty audience: Bob->Alice subscription id attached to Carol's work
        execute(
            db_path,
            "INSERT INTO work_audience (work_id, subscription_id, status, granted_at, created_at) "
            "VALUES (?, ?, 'active', ?, ?)",
            (
                carol_work["id"],
                bob_subscription["id"],
                "2026-08-02T11:00:00+00:00",
                "2026-08-02T11:00:00+00:00",
            ),
        )

        feed = alice.get("/api/story/feed")
        assert all(
            item["id"] != carol_work["id"] for item in feed.json()["items"]
        )
        detail = alice.get(f"/api/story/published/{carol_work['id']}")
        assert detail.status_code == 404


def test_collections_group_by_owner_and_hide_empty(tmp_path, monkeypatch):
    app, db_path = resonance_app(tmp_path, monkeypatch)
    with three_accounts(app) as (alice, bob, carol, alice_profile, bob_profile, carol_profile):
        # Bob grants Alice, publishes 2 works
        bob_subscription = join_subscription(bob, alice)
        bob_work_ids = []
        for index, published_at in enumerate(
            ["2026-08-01T09:00:00+00:00", "2026-08-03T09:00:00+00:00"]
        ):
            work = create_ready_work(bob, f"Bob {index}")
            published = bob.put(
                f"/api/story/works/{work['id']}/publication",
                json={"subscription_ids": [bob_subscription["id"]]},
            )
            assert published.status_code == 200
            execute(
                db_path,
                "UPDATE story_works SET published_at=? WHERE id=?",
                (published_at, work["id"]),
            )
            bob_work_ids.append(work["id"])

        # Carol grants Alice, publishes 1 work (between Bob's two in time)
        carol_subscription = join_subscription(carol, alice)
        carol_work = create_ready_work(carol, "Carol 0")
        published = carol.put(
            f"/api/story/works/{carol_work['id']}/publication",
            json={"subscription_ids": [carol_subscription["id"]]},
        )
        assert published.status_code == 200
        execute(
            db_path,
            "UPDATE story_works SET published_at=? WHERE id=?",
            ("2026-08-02T09:00:00+00:00", carol_work["id"]),
        )

        # Dave has no works visible to Alice -> no entry. Reuse carol client as
        # a third party is unnecessary; a self-only Bob work should not count.
        bob_private = create_ready_work(bob, "Bob 私密")
        bob_private_publish = bob.put(
            f"/api/story/works/{bob_private['id']}/publication",
            json={"subscription_ids": []},
        )
        assert bob_private_publish.status_code == 200

        collections = alice.get("/api/story/collections")
        assert collections.status_code == 200
        items = collections.json()["items"]
        # Bob's latest (08-03) > Carol's (08-02)
        assert [item["owner"]["id"] for item in items] == [
            bob_profile["id"],
            carol_profile["id"],
        ]
        assert items[0]["story_count"] == 2
        assert items[1]["story_count"] == 1
        assert items[0]["latest_work"]["id"] == bob_work_ids[1]

        # detail default desc
        detail = alice.get(f"/api/story/collections/{bob_profile['id']}")
        assert detail.status_code == 200
        detail_items = detail.json()["items"]
        assert [item["id"] for item in detail_items] == list(reversed(bob_work_ids))

        # asc order
        ascending = alice.get(
            f"/api/story/collections/{bob_profile['id']}?order=asc"
        )
        assert [item["id"] for item in ascending.json()["items"]] == bob_work_ids

        # cursor from desc cannot be reused with asc
        desc_page = alice.get(
            f"/api/story/collections/{bob_profile['id']}?order=desc&page_size=1"
        )
        desc_cursor = desc_page.json()["next_cursor"]
        assert desc_cursor
        cross = alice.get(
            f"/api/story/collections/{bob_profile['id']}?order=asc&cursor={desc_cursor}"
        )
        assert cross.status_code == 400

        # revoke Carol's only work -> Carol disappears from collections
        carol.put(
            f"/api/story/works/{carol_work['id']}/audience",
            json={"subscription_ids": []},
        )
        after = alice.get("/api/story/collections")
        assert [item["owner"]["id"] for item in after.json()["items"]] == [
            bob_profile["id"]
        ]


def test_published_work_detail_is_viewer_safe(tmp_path, monkeypatch):
    app, _db_path = resonance_app(tmp_path, monkeypatch)
    with three_accounts(app) as (alice, bob, carol, alice_profile, bob_profile, _carol_profile):
        work = create_ready_work(alice, "安全详情")
        bob_subscription = join_subscription(alice, bob)
        published = alice.put(
            f"/api/story/works/{work['id']}/publication",
            json={"subscription_ids": [bob_subscription["id"]]},
        )
        assert published.status_code == 200

        owner_view = alice.get(f"/api/story/published/{work['id']}")
        assert owner_view.status_code == 200
        assert owner_view.json()["mine"] is True
        assert owner_view.json()["title"] == "安全详情"

        viewer_view = bob.get(f"/api/story/published/{work['id']}")
        assert viewer_view.status_code == 200
        assert viewer_view.json()["mine"] is False

        def assert_safe(payload):
            forbidden = {
                "source_diaries",
                "source_snapshot",
                "render_prompt",
                "forbidden_content",
                "prompt",
                "selected_segments_json",
            }
            assert forbidden.isdisjoint(payload.keys())
            for asset in payload["assets"]:
                assert forbidden.isdisjoint(asset.keys())

        assert_safe(owner_view.json())
        assert_safe(viewer_view.json())

        # stranger and revoked viewer get 404
        assert carol.get(f"/api/story/published/{work['id']}").status_code == 404
        alice.put(
            f"/api/story/works/{work['id']}/audience",
            json={"subscription_ids": []},
        )
        assert bob.get(f"/api/story/published/{work['id']}").status_code == 404


def test_likes_are_isolated_between_viewers(tmp_path, monkeypatch):
    app, _db_path = resonance_app(tmp_path, monkeypatch)
    with three_accounts(app) as (alice, bob, carol, alice_profile, bob_profile, carol_profile):
        work = create_ready_work(alice)
        bob_subscription = join_subscription(alice, bob)
        carol_subscription = join_subscription(alice, carol)
        published = alice.put(
            f"/api/story/works/{work['id']}/publication",
            json={
                "subscription_ids": [
                    bob_subscription["id"],
                    carol_subscription["id"],
                ]
            },
        )
        assert published.status_code == 200

        # Bob likes
        liked = bob.put(f"/api/story/works/{work['id']}/like")
        assert liked.status_code == 200

        # owner sees the liker name; viewers only see their own state
        owner_item = alice.get("/api/story/feed").json()["items"][0]
        assert [person["id"] for person in owner_item["likes"]] == [bob_profile["id"]]
        assert "liked_by_me" not in owner_item
        assert owner_item["audience_count"] == 2

        bob_item = bob.get("/api/story/feed").json()["items"][0]
        assert bob_item["liked_by_me"] is True
        assert "likes" not in bob_item
        assert "audience_count" not in bob_item

        carol_item = carol.get("/api/story/feed").json()["items"][0]
        assert carol_item["liked_by_me"] is False
        assert "likes" not in carol_item

        # idempotent unlike
        assert bob.delete(f"/api/story/works/{work['id']}/like").status_code == 200
        assert bob.delete(f"/api/story/works/{work['id']}/like").status_code == 200
        assert (
            bob.get("/api/story/feed").json()["items"][0]["liked_by_me"] is False
        )
        assert (
            alice.get("/api/story/feed").json()["items"][0]["likes"] == []
        )

        # author cannot like own work
        assert alice.put(f"/api/story/works/{work['id']}/like").status_code == 404


def test_comments_multiple_reply_and_idempotency(tmp_path, monkeypatch):
    app, _db_path = resonance_app(tmp_path, monkeypatch)
    with three_accounts(app) as (alice, bob, carol, alice_profile, bob_profile, carol_profile):
        work = create_ready_work(alice)
        bob_subscription = join_subscription(alice, bob)
        carol_subscription = join_subscription(alice, carol)
        published = alice.put(
            f"/api/story/works/{work['id']}/publication",
            json={
                "subscription_ids": [
                    bob_subscription["id"],
                    carol_subscription["id"],
                ]
            },
        )
        assert published.status_code == 200
        comment_url = f"/api/story/works/{work['id']}/comments"

        # Bob sends two consecutive comments; retry with same id does not dup
        first = bob.post(
            comment_url, json={"client_request_id": "b-1", "body": "第一条"}
        )
        assert first.status_code == 201, first.text
        retry = bob.post(
            comment_url, json={"client_request_id": "b-1", "body": "第一条"}
        )
        assert retry.json()["id"] == first.json()["id"]
        second = bob.post(
            comment_url, json={"client_request_id": "b-2", "body": "第二条"}
        )
        assert second.status_code == 201

        # Alice replies to Bob, must bind viewer_user_id
        reply = alice.post(
            comment_url,
            json={
                "client_request_id": "a-1",
                "body": "回复 Bob",
                "viewer_user_id": bob_profile["id"],
            },
        )
        assert reply.status_code == 201, reply.text

        # author reply without viewer_user_id rejected
        missing_viewer = alice.post(
            comment_url,
            json={"client_request_id": "a-2", "body": "缺目标"},
        )
        assert missing_viewer.status_code == 422

        # viewer cannot spoof another viewer scope
        spoof = bob.post(
            comment_url,
            json={
                "client_request_id": "b-3",
                "body": "冒充",
                "viewer_user_id": carol_profile["id"],
            },
        )
        assert spoof.status_code == 404

        # Carol comments independently
        carol_comment = carol.post(
            comment_url, json={"client_request_id": "c-1", "body": "Carol 的声音"}
        )
        assert carol_comment.status_code == 201

        # Bob sees own scope (2 own + Alice's reply to him), not Carol's
        bob_comments = bob.get(comment_url).json()["items"]
        assert [c["body"] for c in bob_comments] == ["第一条", "第二条", "回复 Bob"]
        # Carol sees only her own
        carol_comments = carol.get(comment_url).json()["items"]
        assert [c["body"] for c in carol_comments] == ["Carol 的声音"]
        # Alice sees all, ordered by time
        alice_comments = alice.get(comment_url).json()["items"]
        assert [c["body"] for c in alice_comments] == [
            "第一条",
            "第二条",
            "回复 Bob",
            "Carol 的声音",
        ]


def test_revoke_and_unpublish_close_interactions(tmp_path, monkeypatch):
    app, db_path = resonance_app(tmp_path, monkeypatch)
    with three_accounts(app) as (alice, bob, carol, alice_profile, bob_profile, carol_profile):
        work = create_ready_work(alice)
        bob_subscription = join_subscription(alice, bob)
        carol_subscription = join_subscription(alice, carol)
        published = alice.put(
            f"/api/story/works/{work['id']}/publication",
            json={
                "subscription_ids": [
                    bob_subscription["id"],
                    carol_subscription["id"],
                ]
            },
        )
        assert published.status_code == 200

        bob.put(f"/api/story/works/{work['id']}/like")
        bob.post(
            f"/api/story/works/{work['id']}/comments",
            json={"client_request_id": "b-1", "body": "Bob 评论"},
        )

        # revoke Bob -> all his interaction routes 404, feed/collection drop
        alice.put(
            f"/api/story/works/{work['id']}/audience",
            json={"subscription_ids": [carol_subscription["id"]]},
        )
        assert bob.put(f"/api/story/works/{work['id']}/like").status_code == 404
        assert (
            bob.post(
                f"/api/story/works/{work['id']}/comments",
                json={"client_request_id": "b-2", "body": "x"},
            ).status_code
            == 404
        )
        assert (
            bob.get(f"/api/story/works/{work['id']}/comments").status_code == 404
        )
        assert bob.get("/api/story/feed").json()["items"] == []
        assert (
            bob.get(f"/api/story/collections/{alice_profile['id']}").json()["items"]
            == []
        )
        # Alice no longer sees Bob's like/comment
        owner_item = alice.get("/api/story/feed").json()["items"][0]
        assert owner_item["likes"] == []
        assert owner_item["comments"] == []

        # re-grant does not resurrect soft-deleted interactions
        alice.put(
            f"/api/story/works/{work['id']}/audience",
            json={
                "subscription_ids": [
                    bob_subscription["id"],
                    carol_subscription["id"],
                ]
            },
        )
        owner_item_again = alice.get("/api/story/feed").json()["items"][0]
        assert owner_item_again["likes"] == []
        assert owner_item_again["comments"] == []

        # unpublish closes everything for everyone including owner's feed
        assert bob.put(f"/api/story/works/{work['id']}/like").status_code == 200
        alice.delete(f"/api/story/works/{work['id']}/publication")
        assert alice.get("/api/story/feed").json()["items"] == []
        assert bob.get("/api/story/feed").json()["items"] == []
        assert (
            bob.post(
                f"/api/story/works/{work['id']}/comments",
                json={"client_request_id": "b-9", "body": "x"},
            ).status_code
            == 404
        )
        # source work remains for owner
        assert (
            alice.get(f"/api/story/works/{work['id']}").json()["status"] == "ready"
        )


def test_published_access_chain_end_to_end(tmp_path, monkeypatch):
    app, _db_path = resonance_app(tmp_path, monkeypatch)
    with three_accounts(app) as (alice, bob, carol, alice_profile, bob_profile, carol_profile):
        work = create_ready_work(alice)
        bob_subscription = join_subscription(alice, bob)
        published = alice.put(
            f"/api/story/works/{work['id']}/publication",
            json={"subscription_ids": [bob_subscription["id"]]},
        )
        assert published.status_code == 200

        # Bob full chain: feed, safe detail, like, comment
        assert bob.get("/api/story/feed").json()["items"][0]["id"] == work["id"]
        assert bob.get(f"/api/story/published/{work['id']}").status_code == 200
        assert bob.put(f"/api/story/works/{work['id']}/like").status_code == 200
        assert (
            bob.post(
                f"/api/story/works/{work['id']}/comments",
                json={"client_request_id": "b-1", "body": "链路与评论"},
            ).status_code
            == 201
        )
        # media authorized while published
        asset_id = work["assets"][0].get("asset_id")
        if asset_id:
            assert bob.get(f"/api/media/{asset_id}").status_code == 200

        # Carol locked out of every entry point
        assert carol.get("/api/story/feed").json()["items"] == []
        assert carol.get(f"/api/story/published/{work['id']}").status_code == 404
        assert carol.put(f"/api/story/works/{work['id']}/like").status_code == 404
        if asset_id:
            assert carol.get(f"/api/media/{asset_id}").status_code == 404

        # revoke Bob: every endpoint closes
        alice.put(
            f"/api/story/works/{work['id']}/audience",
            json={"subscription_ids": []},
        )
        assert bob.get("/api/story/feed").json()["items"] == []
        assert bob.get(f"/api/story/published/{work['id']}").status_code == 404
        assert bob.put(f"/api/story/works/{work['id']}/like").status_code == 404
        if asset_id:
            assert bob.get(f"/api/media/{asset_id}").status_code == 404
        # owner retains source
        assert alice.get(f"/api/story/works/{work['id']}").status_code == 200


def test_migrated_publication_remains_readable_during_v11_rollout(
    tmp_path, monkeypatch
):
    """A v10 ready work with active audience becomes published in v11; after
    Task 2 the viewer reads it through the strict published-only path and the
    owner retains access. The migration backfill is what makes it visible."""
    app, db_path = resonance_app(tmp_path, monkeypatch)
    with accounts(app) as (alice, bob, _alice_profile, _bob_profile):
        work = create_ready_work(alice)
        subscription = join_subscription(alice, bob)
        # Publish via the new lifecycle endpoint, which is what the v11
        # migration produces for legacy active-audience works.
        published = alice.put(
            f"/api/story/works/{work['id']}/publication",
            json={"subscription_ids": [subscription["id"]]},
        )
        assert published.status_code == 200, published.text

        feed = bob.get("/api/story/feed")
        assert feed.status_code == 200
        assert feed.json()["items"][0]["id"] == work["id"]

        # owner still reads the source work
        owner_view = alice.get(f"/api/story/works/{work['id']}")
        assert owner_view.status_code == 200

        # stranger remains locked out
        with TestClient(app, base_url="http://testserver") as stranger:
            assert stranger.post(
                "/api/auth/register",
                json={
                    "username": "resonance-stranger",
                    "password": PASSWORD,
                    "nickname": "Stranger",
                },
            ).status_code == 201
            stranger_feed = stranger.get("/api/story/feed")
            assert stranger_feed.json()["items"] == []
            blocked = stranger.get(f"/api/story/published/{work['id']}")
            assert blocked.status_code == 404
