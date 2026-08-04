import base64
import hashlib
import importlib
import ipaddress
import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from uuid import UUID

import httpx
import pytest
from fastapi.testclient import TestClient


PASSWORD = "correct horse battery"
FOREIGN_ORIGIN = "https://attacker.example"
PNG_BYTES = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk"
    "/wcAAusB9Wl2nWQAAAAASUVORK5CYII="
)
PNG_DATA_URL = "data:image/png;base64," + base64.b64encode(PNG_BYTES).decode()


class FakeNetworkStream:
    def __init__(self, server_addr):
        self.server_addr = server_addr

    def get_extra_info(self, name):
        if name == "server_addr":
            return self.server_addr
        return None


@pytest.fixture
def media_app(tmp_path, monkeypatch):
    db_path = tmp_path / "media.sqlite3"
    upload_dir = tmp_path / "uploads"
    monkeypatch.setenv("ZHIJI_DB_PATH", str(db_path))
    monkeypatch.setenv("ZHIJI_UPLOAD_DIR", str(upload_dir))
    monkeypatch.setenv("FRONTEND_ORIGINS", "http://localhost:5173")
    monkeypatch.setenv("SESSION_COOKIE_SECURE", "false")
    monkeypatch.setenv("MEDIA_MAX_BYTES", "128")
    monkeypatch.delenv("MEDIA_ALLOW_PRIVATE_HOSTS", raising=False)

    import config
    import database
    import main
    import agents.diary_agent

    importlib.reload(config)
    importlib.reload(database)
    for module_name in (
        "services.room_access",
        "routers.upload",
        "routers.profile",
        "routers.fragments",
        "routers.image",
        "routers.weekly_comic",
        "routers.dual_timeline",
    ):
        importlib.reload(importlib.import_module(module_name))

    async def fake_description(*_args, **_kwargs):
        return "one pixel"

    monkeypatch.setattr(agents.diary_agent, "describe_photo", fake_description)
    app = importlib.reload(main).app
    return app, db_path, upload_dir


@contextmanager
def clients(app, count=2):
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


def upload_png(client, filename="family photo.png"):
    response = client.post(
        "/api/upload",
        files={"file": (filename, PNG_BYTES, "image/png")},
    )
    assert response.status_code == 200, response.text
    return response.json()


def execute(db_path, sql, params=()):
    with sqlite3.connect(db_path) as db:
        db.execute(sql, params)
        db.commit()


def fetch_all(db_path, sql, params=()):
    with sqlite3.connect(db_path) as db:
        db.row_factory = sqlite3.Row
        return db.execute(sql, params).fetchall()


def seed_pair(db_path, owner_id, partner_id, room_id="media-room"):
    with sqlite3.connect(db_path) as db:
        db.execute(
            "INSERT INTO rooms (id, creator_user_id, status) VALUES (?, ?, 'active')",
            (room_id, owner_id),
        )
        db.executemany(
            "INSERT INTO room_members (room_id, user_id, role, slot) "
            "VALUES (?, ?, ?, ?)",
            [
                (room_id, owner_id, "owner", 1),
                (room_id, partner_id, "member", 2),
            ],
        )
        db.commit()
    return room_id


def seed_published_media_post(db_path, room_id, owner_id, asset_id):
    snapshot = json.dumps({"body": "shared"}, sort_keys=True)
    with sqlite3.connect(db_path) as db:
        db.execute(
            "INSERT INTO room_posts "
            "(id, room_id, author_user_id, source_type, source_id, "
            "source_revision, snapshot_hash, snapshot_json, status) "
            "VALUES ('media-post', ?, ?, 'note', NULL, NULL, ?, ?, 'published')",
            (
                room_id,
                owner_id,
                hashlib.sha256(snapshot.encode()).hexdigest(),
                snapshot,
            ),
        )
        db.execute(
            "INSERT INTO room_post_media (post_id, asset_id, ordinal) "
            "VALUES ('media-post', ?, 0)",
            (asset_id,),
        )
        db.commit()


def test_upload_creates_opaque_owned_asset_and_protected_url(media_app):
    app, db_path, upload_dir = media_app
    with clients(app, 3) as (owner, stranger, anonymous):
        owner_profile = register(owner, "media-owner", "Owner")
        register(stranger, "media-stranger", "Stranger")

        assert anonymous.post(
            "/api/upload",
            files={"file": ("anonymous.png", PNG_BYTES, "image/png")},
        ).status_code == 401
        assert owner.post(
            "/api/upload",
            files={"file": ("origin.png", PNG_BYTES, "image/png")},
            headers={"Origin": FOREIGN_ORIGIN},
        ).status_code == 403

        uploaded = upload_png(owner)
        assert set(uploaded) == {"asset_id", "url", "photo_description"}
        UUID(uploaded["asset_id"])
        assert uploaded["url"] == f"/api/media/{uploaded['asset_id']}"
        assert uploaded["photo_description"] == "one pixel"

        owner_read = owner.get(uploaded["url"])
        assert owner_read.status_code == 200
        assert owner_read.content == PNG_BYTES
        assert owner_read.headers["content-type"].startswith("image/png")
        assert anonymous.get(uploaded["url"]).status_code == 401
        assert stranger.get(uploaded["url"]).status_code == 404

    rows = fetch_all(db_path, "SELECT * FROM media_assets")
    assert len(rows) == 1
    assert rows[0]["id"] == uploaded["asset_id"]
    assert rows[0]["owner_user_id"] == owner_profile["id"]
    assert rows[0]["mime_type"] == "image/png"
    assert rows[0]["size_bytes"] == len(PNG_BYTES)
    assert "family" not in rows[0]["storage_key"]
    assert "/" not in rows[0]["storage_key"]
    assert (upload_dir / rows[0]["storage_key"]).read_bytes() == PNG_BYTES


def test_profile_and_fragment_only_attach_current_users_assets(media_app):
    app, db_path, _ = media_app
    with clients(app) as (alice, bob):
        alice_profile = register(alice, "asset-alice", "Alice")
        register(bob, "asset-bob", "Bob")
        alice_asset = upload_png(alice, "alice.png")
        bob_asset = upload_png(bob, "bob.png")

        assert alice.put(
            "/api/profile", json={"avatar_asset_id": bob_asset["asset_id"]}
        ).status_code == 404
        assert alice.put(
            "/api/profile", json={"avatar_url": bob_asset["url"]}
        ).status_code == 404
        own_profile = alice.put(
            "/api/profile", json={"avatar_asset_id": alice_asset["asset_id"]}
        )
        assert own_profile.status_code == 200
        assert own_profile.json()["avatar_asset_id"] == alice_asset["asset_id"]
        assert own_profile.json()["avatar_url"] == alice_asset["url"]

        assert alice.post(
            "/api/fragments",
            json={
                "date": "2026-08-03",
                "photo_asset_id": bob_asset["asset_id"],
            },
        ).status_code == 404
        own_fragment = alice.post(
            "/api/fragments",
            json={"date": "2026-08-03", "photo_url": alice_asset["url"]},
        )
        assert own_fragment.status_code == 200
        assert own_fragment.json()["photo_asset_id"] == alice_asset["asset_id"]
        assert own_fragment.json()["photo_url"] == alice_asset["url"]

        assert alice.put(
            "/api/profile",
            json={"avatar_url": "https://attacker.example/avatar.png"},
        ).status_code == 400
        assert alice.post(
            "/api/fragments",
            json={
                "date": "2026-08-04",
                "photo_url": "/api/upload/unproven.png",
            },
        ).status_code == 400

    stored = fetch_all(
        db_path,
        "SELECT avatar_asset_id FROM profile WHERE id=?",
        (alice_profile["id"],),
    )[0]
    assert stored["avatar_asset_id"] == alice_asset["asset_id"]


def test_partner_media_requires_active_published_relation(media_app):
    app, db_path, _ = media_app
    with clients(app, 3) as (owner, partner, stranger):
        owner_profile = register(owner, "post-owner", "Owner")
        partner_profile = register(partner, "post-partner", "Partner")
        register(stranger, "post-stranger", "Stranger")
        uploaded = upload_png(owner)
        room_id = seed_pair(
            db_path, owner_profile["id"], partner_profile["id"]
        )

        assert partner.get(uploaded["url"]).status_code == 404
        seed_published_media_post(
            db_path, room_id, owner_profile["id"], uploaded["asset_id"]
        )
        assert partner.get(uploaded["url"]).content == PNG_BYTES
        assert stranger.get(uploaded["url"]).status_code == 404

        execute(
            db_path,
            "UPDATE room_posts SET status='revoked', revoked_at=CURRENT_TIMESTAMP "
            "WHERE id='media-post'",
        )
        assert partner.get(uploaded["url"]).status_code == 404
        assert owner.get(uploaded["url"]).status_code == 200

        execute(
            db_path,
            "UPDATE room_posts SET status='published', revoked_at=NULL "
            "WHERE id='media-post'",
        )
        execute(
            db_path,
            "UPDATE rooms SET status='closed', closed_at=CURRENT_TIMESTAMP WHERE id=?",
            (room_id,),
        )
        assert partner.get(uploaded["url"]).status_code == 404
        assert owner.get(uploaded["url"]).status_code == 200


def test_active_partner_avatar_is_canonical_and_revoked_on_leave(media_app):
    app, db_path, _ = media_app
    with clients(app, 3) as (owner, partner, stranger):
        owner_profile = register(owner, "avatar-owner", "Owner")
        partner_profile = register(partner, "avatar-partner", "Partner")
        register(stranger, "avatar-stranger", "Stranger")
        uploaded = upload_png(owner)
        assert owner.put(
            "/api/profile", json={"avatar_asset_id": uploaded["asset_id"]}
        ).status_code == 200
        room_id = seed_pair(
            db_path, owner_profile["id"], partner_profile["id"], "avatar-room"
        )

        room = partner.get("/api/rooms/current")
        assert room.status_code == 200
        assert room.json()["partner"]["avatar_url"] == uploaded["url"]
        assert partner.get(uploaded["url"]).status_code == 200
        assert stranger.get(uploaded["url"]).status_code == 404

        execute(
            db_path,
            "UPDATE room_members SET left_at=CURRENT_TIMESTAMP "
            "WHERE room_id=? AND user_id=?",
            (room_id, partner_profile["id"]),
        )
        assert partner.get(uploaded["url"]).status_code == 404
        assert owner.get(uploaded["url"]).status_code == 200


@pytest.mark.parametrize(
    ("filename", "seed_sql", "seed_params"),
    [
        (
            "profile.png",
            "UPDATE profile SET avatar_url='/api/upload/profile.png' WHERE id=?",
            lambda user_id: (user_id,),
        ),
        (
            "fragment.png",
            "INSERT INTO fragments (date, photo_url, user_id) "
            "VALUES ('2026-08-03', '/api/upload/fragment.png', ?)",
            lambda user_id: (user_id,),
        ),
        (
            "diary.png",
            "INSERT INTO images (diary_id, url) "
            "VALUES ((SELECT id FROM diaries WHERE user_id=? LIMIT 1), "
            "'/api/upload/diary.png')",
            lambda user_id: (user_id,),
        ),
        (
            "weekly.png",
            "INSERT INTO weekly_comics "
            "(user_id, week_start, week_end, url) "
            "VALUES (?, '2026-08-03', '2026-08-03', '/api/upload/weekly.png')",
            lambda user_id: (user_id,),
        ),
        (
            "dual.png",
            "INSERT INTO dual_timeline_comics "
            "(date, user_a_id, user_b_id, url) "
            "VALUES ('2026-08-03', ?, ?, '/api/upload/dual.png')",
            lambda user_id: (user_id, user_id + 1),
        ),
    ],
)
def test_legacy_upload_requires_authenticated_source_ownership(
    media_app, filename, seed_sql, seed_params
):
    app, db_path, upload_dir = media_app
    with clients(app, 3) as (owner, stranger, anonymous):
        owner_profile = register(owner, f"legacy-{filename}", "Owner")
        register(stranger, f"stranger-{filename}", "Stranger")
        if filename == "diary.png":
            diary = owner.post(
                "/api/diary", json={"date": "2026-08-03"}
            )
            assert diary.status_code == 200
        upload_dir.mkdir(parents=True, exist_ok=True)
        (upload_dir / filename).write_bytes(PNG_BYTES)
        execute(db_path, seed_sql, seed_params(owner_profile["id"]))

        assert owner.get(f"/api/upload/{filename}").content == PNG_BYTES
        assert stranger.get(f"/api/upload/{filename}").status_code == 404
        assert anonymous.get(f"/api/upload/{filename}").status_code == 401
        assert owner.get("/api/upload/%2e%2e%2fsecret.png").status_code == 404


def test_generated_data_local_and_remote_outputs_become_owned_assets(
    media_app, monkeypatch
):
    app, db_path, upload_dir = media_app
    import agents.image_agent
    import routers.dual_timeline as dual_router
    import routers.weekly_comic as weekly_router

    async def fake_batch(**_kwargs):
        return [PNG_DATA_URL]

    async def fake_weekly_plan(**_kwargs):
        return "weekly prompt", "weekly caption"

    async def fake_weekly_image(**_kwargs):
        upload_dir.mkdir(parents=True, exist_ok=True)
        (upload_dir / "generated-local.png").write_bytes(PNG_BYTES)
        return "/api/upload/generated-local.png"

    async def fake_summary(*_args, **_kwargs):
        return "summary"

    async def fake_dual_plan(**_kwargs):
        return "dual prompt", "dual caption"

    async def fake_remote_image(**_kwargs):
        return "https://images.example/generated.png"

    async def fake_download(_url, *, client=None):
        return PNG_BYTES, "image/png"

    monkeypatch.setattr(agents.image_agent, "generate_batch", fake_batch)
    monkeypatch.setattr(weekly_router, "plan_weekly_comic", fake_weekly_plan)
    monkeypatch.setattr(weekly_router, "generate_image", fake_weekly_image)
    monkeypatch.setattr(dual_router, "summarize", fake_summary)
    monkeypatch.setattr(dual_router, "plan_comic", fake_dual_plan)
    monkeypatch.setattr(dual_router, "generate_image", fake_remote_image)
    media_store = importlib.import_module("services.media_store")
    monkeypatch.setattr(media_store, "download_remote", fake_download)

    with clients(app, 2) as (alice, bob):
        alice_profile = register(alice, "generated-media", "Alice")
        bob_profile = register(bob, "generated-partner", "Bob")
        seed_pair(db_path, alice_profile["id"], bob_profile["id"], "gen-room")
        diary = alice.post("/api/diary", json={"date": "2026-08-03"}).json()
        assert alice.put(
            f"/api/diary/{diary['id']}", json={"text": "draw this"}
        ).status_code == 200
        assert alice.post(
            "/api/schedules",
            json={"date": "2026-08-03", "time": "08:00", "title": "work"},
        ).status_code == 200

        image = alice.post(
            f"/api/image/diary/{diary['id']}/images/batch",
            json={"style": "ghibli", "n": 1},
        )
        weekly = alice.post(
            "/api/weekly-comic/generate",
            json={
                "week_start": "2026-08-03",
                "week_end": "2026-08-03",
                "style": "ghibli",
            },
        )
        timeline = alice.get(
            "/api/dual-timeline", params={"date": "2026-08-03"}
        ).json()
        dual = alice.post(
            "/api/dual-timeline/comic/generate",
            json={
                "date": "2026-08-03",
                "selected_a": [timeline["events_a"][0]],
                "selected_b": [],
                "style": "ghibli",
            },
        )

    for response in (image, weekly, dual):
        assert response.status_code == 200, response.text
    rows = fetch_all(
        db_path,
        "SELECT owner_user_id, id, storage_key FROM media_assets ORDER BY created_at",
    )
    assert len(rows) == 3
    assert {row["owner_user_id"] for row in rows} == {alice_profile["id"]}
    for table in ("images", "weekly_comics", "dual_timeline_comics"):
        source = fetch_all(db_path, f"SELECT url, asset_id FROM {table}")[0]
        assert source["asset_id"] is not None
        assert source["url"] == f"/api/media/{source['asset_id']}"


@pytest.mark.asyncio
async def test_remote_download_rejects_missing_connected_peer_metadata(
    media_app, monkeypatch
):
    _, _, upload_dir = media_app
    import database
    from services import media_store

    async def public_dns(_host, _port):
        return [ipaddress.ip_address("93.184.216.34")]

    monkeypatch.setattr(media_store, "_resolve_host", public_dns)

    def image_without_peer(request):
        return httpx.Response(
            200,
            headers={"content-type": "image/png"},
            content=PNG_BYTES,
        )

    network_client = httpx.AsyncClient(
        transport=httpx.MockTransport(image_without_peer)
    )
    monkeypatch.setattr(
        media_store.httpx,
        "AsyncClient",
        lambda **_kwargs: network_client,
    )

    db = await database.get_db()
    try:
        await database.init_db(db)
        await db.commit()
        with pytest.raises(media_store.RemoteMediaBlocked, match="peer"):
            async with media_store.staged_generated_media(db) as media_stage:
                await media_store.store_generated_asset(
                    db,
                    99999,
                    "https://example.com/image.png",
                    stage=media_stage,
                )
        cursor = await db.execute("SELECT COUNT(*) AS count FROM media_assets")
        assert (await cursor.fetchone())["count"] == 0
    finally:
        await db.close()

    assert not list(upload_dir.glob("*"))


@pytest.mark.asyncio
async def test_remote_download_accepts_verified_global_connected_peer(
    media_app, monkeypatch
):
    from services import media_store

    observed = {}

    async def public_dns(_host, _port):
        return [ipaddress.ip_address("93.184.216.34")]

    monkeypatch.setattr(media_store, "_resolve_host", public_dns)

    def image_with_public_peer(request):
        observed.update(
            url_host=request.url.host,
            host_header=request.headers["host"],
            sni_hostname=request.extensions.get("sni_hostname"),
        )
        return httpx.Response(
            200,
            headers={"content-type": "image/png"},
            content=PNG_BYTES,
            extensions={
                "network_stream": FakeNetworkStream(("93.184.216.34", 443))
            },
        )

    content, mime_type = await media_store.download_remote(
        "https://example.com/image.png",
        transport=httpx.MockTransport(image_with_public_peer),
    )

    assert content == PNG_BYTES
    assert mime_type == "image/png"
    assert observed == {
        "url_host": "93.184.216.34",
        "host_header": "example.com",
        "sni_hostname": "example.com",
    }


@pytest.mark.asyncio
async def test_remote_download_pins_ipv6_with_port_and_original_tls_identity(
    media_app, monkeypatch
):
    from services import media_store

    vetted_ip = ipaddress.ip_address("2001:4860:4860::8888")
    observed = {}

    async def public_dns(_host, _port):
        return [vetted_ip]

    monkeypatch.setattr(media_store, "_resolve_host", public_dns)

    def image_with_vetted_peer(request):
        observed.update(
            url_host=request.url.host,
            url_port=request.url.port,
            host_header=request.headers["host"],
            sni_hostname=request.extensions.get("sni_hostname"),
        )
        return httpx.Response(
            200,
            headers={"content-type": "image/png"},
            content=PNG_BYTES,
            extensions={
                "network_stream": FakeNetworkStream((str(vetted_ip), 8443))
            },
        )

    await media_store.download_remote(
        "https://media.example:8443/image.png?size=small",
        transport=httpx.MockTransport(image_with_vetted_peer),
    )

    assert observed == {
        "url_host": str(vetted_ip),
        "url_port": 8443,
        "host_header": "media.example:8443",
        "sni_hostname": "media.example",
    }


@pytest.mark.asyncio
async def test_remote_download_dev_private_opt_in_still_pins_exact_peer(
    media_app, monkeypatch
):
    from services import media_store

    monkeypatch.setenv("MEDIA_ALLOW_PRIVATE_HOSTS", "true")
    private_ip = ipaddress.ip_address("127.0.0.1")

    async def private_dns(_host, _port):
        return [private_ip]

    monkeypatch.setattr(media_store, "_resolve_host", private_dns)

    def image_with_private_peer(request):
        assert request.url.host == str(private_ip)
        assert request.headers["host"] == "dev-media.example"
        return httpx.Response(
            200,
            headers={"content-type": "image/png"},
            content=PNG_BYTES,
            extensions={
                "network_stream": FakeNetworkStream((str(private_ip), 443))
            },
        )

    content, _ = await media_store.download_remote(
        "https://dev-media.example/image.png",
        transport=httpx.MockTransport(image_with_private_peer),
    )
    assert content == PNG_BYTES


@pytest.mark.asyncio
async def test_remote_download_rejects_peer_that_differs_from_pinned_ip(
    media_app, monkeypatch
):
    _, _, upload_dir = media_app
    import database
    from services import media_store

    async def public_dns(_host, _port):
        return [ipaddress.ip_address("93.184.216.34")]

    monkeypatch.setattr(media_store, "_resolve_host", public_dns)

    def image_from_different_public_peer(request):
        return httpx.Response(
            200,
            headers={"content-type": "image/png"},
            content=PNG_BYTES,
            extensions={
                "network_stream": FakeNetworkStream(("1.1.1.1", 443))
            },
        )

    network_client = httpx.AsyncClient(
        transport=httpx.MockTransport(image_from_different_public_peer)
    )
    monkeypatch.setattr(
        media_store.httpx,
        "AsyncClient",
        lambda **_kwargs: network_client,
    )

    db = await database.get_db()
    try:
        await database.init_db(db)
        await db.commit()
        with pytest.raises(media_store.RemoteMediaBlocked, match="peer"):
            async with media_store.staged_generated_media(db) as media_stage:
                await media_store.store_generated_asset(
                    db,
                    99999,
                    "https://example.com/image.png",
                    stage=media_stage,
                )
        cursor = await db.execute("SELECT COUNT(*) AS count FROM media_assets")
        assert (await cursor.fetchone())["count"] == 0
    finally:
        await db.close()

    assert not list(upload_dir.glob("*"))


def test_generated_batch_rolls_back_all_media_when_later_output_is_invalid(
    media_app, monkeypatch
):
    app, db_path, upload_dir = media_app
    import agents.image_agent

    async def valid_then_invalid(**_kwargs):
        return [PNG_DATA_URL, "data:image/png;base64,%%%"]

    monkeypatch.setattr(agents.image_agent, "generate_batch", valid_then_invalid)

    with clients(app, 1) as (client,):
        register(client, "atomic-batch", "Atomic")
        diary = client.post("/api/diary", json={"date": "2026-08-04"}).json()
        assert client.put(
            f"/api/diary/{diary['id']}", json={"text": "draw both"}
        ).status_code == 200
        response = client.post(
            f"/api/image/diary/{diary['id']}/images/batch",
            json={"style": "ghibli", "n": 2},
        )

    assert response.status_code == 400
    assert not fetch_all(db_path, "SELECT id FROM media_assets")
    assert not fetch_all(db_path, "SELECT id FROM images")
    assert not list(upload_dir.glob("*"))


def test_generated_batch_cleans_staged_media_when_source_insert_fails(
    media_app, monkeypatch
):
    app, db_path, upload_dir = media_app
    import agents.image_agent

    async def one_valid_output(**_kwargs):
        return [PNG_DATA_URL]

    monkeypatch.setattr(agents.image_agent, "generate_batch", one_valid_output)

    with TestClient(
        app,
        base_url="http://testserver",
        raise_server_exceptions=False,
    ) as client:
        register(client, "atomic-source", "Atomic")
        diary = client.post("/api/diary", json={"date": "2026-08-04"}).json()
        assert client.put(
            f"/api/diary/{diary['id']}", json={"text": "draw once"}
        ).status_code == 200
        execute(
            db_path,
            "CREATE TRIGGER fail_image_insert BEFORE INSERT ON images "
            "BEGIN SELECT RAISE(ABORT, 'forced source insert failure'); END",
        )
        response = client.post(
            f"/api/image/diary/{diary['id']}/images/batch",
            json={"style": "ghibli", "n": 1},
        )

    assert response.status_code == 500
    assert not fetch_all(db_path, "SELECT id FROM media_assets")
    assert not fetch_all(db_path, "SELECT id FROM images")
    assert not list(upload_dir.glob("*"))


@pytest.mark.asyncio
async def test_generated_media_commit_failure_rolls_back_row_and_file(
    media_app, monkeypatch
):
    app, db_path, upload_dir = media_app
    import database
    from services import media_store

    with clients(app, 1) as (client,):
        owner = register(client, "atomic-commit", "Atomic")

    db = await database.get_db()

    async def fail_commit():
        raise RuntimeError("forced commit failure")

    monkeypatch.setattr(db, "commit", fail_commit)
    try:
        with pytest.raises(RuntimeError, match="forced commit failure"):
            async with media_store.staged_generated_media(db) as media_stage:
                await media_store.store_generated_asset(
                    db,
                    owner["id"],
                    PNG_DATA_URL,
                    stage=media_stage,
                )
    finally:
        await db.close()

    assert not fetch_all(db_path, "SELECT id FROM media_assets")
    assert not list(upload_dir.glob("*"))


@pytest.mark.asyncio
async def test_media_store_rejects_invalid_inputs_and_cleans_failed_writes(
    media_app, monkeypatch
):
    _, _, upload_dir = media_app
    import config
    import database
    from services import media_store

    db = await database.get_db()
    try:
        with pytest.raises(media_store.UnsupportedMediaType):
            await media_store.store_bytes(db, 99999, b"plain", "text/plain")
        with pytest.raises(media_store.MediaTooLarge):
            await media_store.store_bytes(db, 99999, b"x" * 129, "image/png")
        with pytest.raises(Exception):
            await media_store.store_bytes(db, 99999, PNG_BYTES, "image/png")
    finally:
        await db.close()
    assert not list(upload_dir.glob("*"))

    with pytest.raises(media_store.InvalidMedia):
        await media_store.materialize_generated("data:image/png;base64,%%%")
    with pytest.raises(media_store.InvalidMedia):
        await media_store.materialize_generated("/api/upload/../secret.png")
    with pytest.raises(media_store.InvalidMedia):
        await media_store.materialize_generated("file:///tmp/secret.png")
    with pytest.raises(media_store.RemoteMediaBlocked):
        await media_store.download_remote("http://127.0.0.1/image.png")
    with pytest.raises(media_store.InvalidMedia):
        await media_store.download_remote("ftp://example.com/image.png")

    async def public_dns(_host, _port):
        return [ipaddress.ip_address("93.184.216.34")]

    monkeypatch.setattr(media_store, "_resolve_host", public_dns)

    def redirect_handler(request):
        return httpx.Response(302, headers={"location": "https://example.com/next"})

    with pytest.raises(media_store.InvalidMedia):
        await media_store.download_remote(
            "https://example.com/image.png",
            transport=httpx.MockTransport(redirect_handler),
        )

    def oversized_handler(request):
        return httpx.Response(
            200,
            headers={"content-type": "image/png"},
            content=b"x" * (config.get_media_max_bytes() + 1),
            extensions={
                "network_stream": FakeNetworkStream(("93.184.216.34", 443))
            },
        )

    with pytest.raises(media_store.MediaTooLarge):
        await media_store.download_remote(
            "https://example.com/image.png",
            transport=httpx.MockTransport(oversized_handler),
        )


def test_upload_rejects_bad_mime_and_oversized_file(media_app):
    app, _, _ = media_app
    with clients(app, 1) as (client,):
        register(client, "media-validation", "Validation")
        bad_mime = client.post(
            "/api/upload",
            files={"file": ("bad.txt", b"not an image", "text/plain")},
        )
        oversized = client.post(
            "/api/upload",
            files={"file": ("large.png", b"x" * 129, "image/png")},
        )
    assert bad_mime.status_code == 415
    assert oversized.status_code == 413
