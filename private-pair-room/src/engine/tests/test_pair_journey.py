import base64
import importlib
import ipaddress
from contextlib import asynccontextmanager, contextmanager

import httpx
import pytest
from fastapi.testclient import TestClient


PASSWORD = "correct horse battery"
RECORD_DATE = "2026-08-04"
DIARY_TEXT = "你在晨会上把难题拆开，午后也记得抬头看窗边的光。回家前，你想给家里打个电话。"
PNG_BYTES = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01"
    b"\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15\xc4\x89"
)
PNG_B64 = base64.b64encode(PNG_BYTES).decode("ascii")
REMOTE_IMAGE_URL = "https://cdn.example/generated.png"
REMOTE_IMAGE_IP = ipaddress.ip_address("93.184.216.34")


class FakeNetworkStream:
    def get_extra_info(self, name):
        if name in {"server_addr", "peername"}:
            return str(REMOTE_IMAGE_IP), 443
        return None


class ExternalState:
    def __init__(self):
        self.diary_calls = []
        self.image_calls = []
        self.remote_requests = []


class FakeExternalAsyncClient:
    """Replace only external HTTP I/O while preserving agent/media logic."""

    def __init__(self, state, **_kwargs):
        self.state = state

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):
        await self.aclose()

    async def aclose(self):
        return None

    async def post(self, url, **kwargs):
        request = httpx.Request("POST", url)
        if url.endswith("/chat/completions"):
            self.state.diary_calls.append({"url": url, **kwargs})
            payload = {"choices": [{"message": {"content": DIARY_TEXT}}]}
        elif url.endswith("/images/generations"):
            call_index = len(self.state.image_calls)
            self.state.image_calls.append({"url": url, **kwargs})
            source = (
                {"b64_json": PNG_B64}
                if call_index == 0
                else {"url": REMOTE_IMAGE_URL}
            )
            payload = {"data": [source]}
        else:
            raise AssertionError(f"unexpected external POST: {url}")
        return httpx.Response(200, request=request, json=payload)

    def stream(self, method, url, **kwargs):
        @asynccontextmanager
        async def response_context():
            request = httpx.Request(method, url, headers=kwargs.get("headers"))
            self.state.remote_requests.append(
                {
                    "method": method,
                    "url": url,
                    "host": request.headers.get("host"),
                    "sni_hostname": (kwargs.get("extensions") or {}).get(
                        "sni_hostname"
                    ),
                    "follow_redirects": kwargs.get("follow_redirects"),
                }
            )
            yield httpx.Response(
                200,
                request=request,
                headers={"content-type": "image/png"},
                content=PNG_BYTES,
                extensions={"network_stream": FakeNetworkStream()},
            )

        return response_context()


@pytest.fixture
def pair_journey_app(tmp_path, monkeypatch):
    db_path = tmp_path / "pair-journey.sqlite3"
    monkeypatch.setenv("ZHIJI_DB_PATH", str(db_path))
    monkeypatch.setenv("ZHIJI_UPLOAD_DIR", str(tmp_path / "uploads"))
    monkeypatch.setenv("FRONTEND_ORIGINS", "http://localhost:5173")
    monkeypatch.setenv("SESSION_COOKIE_SECURE", "false")
    monkeypatch.setenv("DIARY_API_BASE_URL", "https://diary.example/v1")
    monkeypatch.setenv("DIARY_API_KEY", "test-diary-key")
    monkeypatch.setenv("DIARY_MODEL", "test-diary-model")
    monkeypatch.setenv("IMAGE_API_BASE_URL", "https://image.example/v1")
    monkeypatch.setenv("IMAGE_API_KEY", "test-image-key")
    monkeypatch.setenv("IMAGE_MODEL", "test-image-model")
    monkeypatch.setenv("MEDIA_ALLOW_PRIVATE_HOSTS", "false")

    import config
    import database
    import main
    import agents.diary_agent
    import agents.image_agent
    import routers.diary
    import routers.image
    import routers.rooms
    import routers.thermometer
    import services.media_store

    importlib.reload(config)
    importlib.reload(database)
    importlib.reload(agents.diary_agent)
    importlib.reload(agents.image_agent)
    importlib.reload(routers.thermometer)
    importlib.reload(routers.diary)
    importlib.reload(routers.image)
    rooms_router = importlib.reload(routers.rooms)
    media_store = importlib.reload(services.media_store)
    app = importlib.reload(main).app

    state = ExternalState()
    monkeypatch.setattr(
        httpx,
        "AsyncClient",
        lambda **kwargs: FakeExternalAsyncClient(state, **kwargs),
    )

    async def public_dns(host, port):
        assert (host, port) == ("cdn.example", 443)
        return [REMOTE_IMAGE_IP]

    monkeypatch.setattr(media_store, "_resolve_host", public_dns)

    async def deterministic_temperature(inputs):
        assert inputs["nickname"] == "Alice"
        assert [item["title"] for item in inputs["schedules"]] == [
            "finish private report"
        ]
        assert [item["content"] for item in inputs["fragments"]] == [
            "private lunch detail"
        ]
        return {
            "nickname": inputs["nickname"],
            "score": 72,
            "label": "温暖",
            "color": "#E89D7B",
            "comment": "private computed comment",
            "quant_score": 32,
            "ai_score": 40,
            "inputs": {"private": True},
        }

    monkeypatch.setattr(
        rooms_router, "compute_temperature", deterministic_temperature
    )
    return app, state


@contextmanager
def paired_clients(app):
    alice = TestClient(
        app, base_url="http://testserver", raise_server_exceptions=False
    )
    bob = TestClient(
        app, base_url="http://testserver", raise_server_exceptions=False
    )
    try:
        alice.__enter__()
        bob.__enter__()
        yield alice, bob
    finally:
        bob.__exit__(None, None, None)
        alice.__exit__(None, None, None)


def register(client, username, nickname):
    response = client.post(
        "/api/auth/register",
        json={"username": username, "password": PASSWORD, "nickname": nickname},
    )
    assert response.status_code == 201, response.text
    return response.json()


def assert_private_source_is_hidden(bob, schedule_id, fragment_id, diary_id):
    assert bob.get("/api/schedules", params={"date": RECORD_DATE}).json() == []
    assert bob.get("/api/fragments", params={"date": RECORD_DATE}).json() == []
    assert bob.get("/api/diary", params={"date": RECORD_DATE}).json() is None
    assert bob.put(
        f"/api/schedules/{schedule_id}", json={"title": "stolen"}
    ).status_code == 404
    assert bob.put(
        f"/api/fragments/{fragment_id}", json={"content": "stolen"}
    ).status_code == 404
    assert bob.put(
        f"/api/diary/{diary_id}", json={"text": "stolen"}
    ).status_code == 404
    assert bob.post(
        f"/api/image/diary/{diary_id}/images/batch",
        json={"style": "ghibli", "n": 1},
    ).status_code == 404


def test_two_accounts_complete_private_pair_share_interact_and_close_journey(
    pair_journey_app,
):
    app, external = pair_journey_app
    with paired_clients(app) as (alice, bob):
        alice_profile = register(alice, "journey-alice", "Alice")
        bob_profile = register(bob, "journey-bob", "Bob")
        assert alice.get("/api/me").json()["id"] == alice_profile["id"]
        assert bob.get("/api/me").json()["id"] == bob_profile["id"]

        created_room = alice.post("/api/rooms")
        assert created_room.status_code == 201, created_room.text
        room_id = created_room.json()["id"]
        invite = alice.post(f"/api/rooms/{room_id}/invites")
        assert invite.status_code == 201, invite.text
        joined = bob.post(
            "/api/room-invites/join", json={"code": invite.json()["code"]}
        )
        assert joined.status_code == 200, joined.text
        assert joined.json()["partner"]["nickname"] == "Alice"
        assert alice.get("/api/rooms/current").json()["partner"]["nickname"] == "Bob"

        schedule = alice.post(
            "/api/schedules",
            json={
                "date": RECORD_DATE,
                "time": "09:00",
                "title": "finish private report",
                "feeling": "focused",
            },
        )
        assert schedule.status_code == 200, schedule.text
        assert alice.put(
            f"/api/schedules/{schedule.json()['id']}", json={"completed": True}
        ).status_code == 200
        fragment = alice.post(
            "/api/fragments",
            json={
                "date": RECORD_DATE,
                "content": "private lunch detail",
                "mood_tag": "steady",
            },
        )
        assert fragment.status_code == 200, fragment.text
        diary = alice.post("/api/diary", json={"date": RECORD_DATE})
        assert diary.status_code == 200, diary.text
        diary_id = diary.json()["id"]

        assert_private_source_is_hidden(
            bob, schedule.json()["id"], fragment.json()["id"], diary_id
        )

        filled = alice.post(
            f"/api/diary/{diary_id}/ai-fill", json={"emotion_mode": "warm"}
        )
        assert filled.status_code == 200, filled.text
        assert filled.json()["text"] == DIARY_TEXT
        assert len(external.diary_calls) == 1
        diary_prompt = external.diary_calls[0]["json"]["messages"][1]["content"]
        assert "finish private report" in diary_prompt
        assert "private lunch detail" in diary_prompt

        generated = alice.post(
            f"/api/image/diary/{diary_id}/images/batch",
            json={"style": "ghibli", "n": 2},
        )
        assert generated.status_code == 200, generated.text
        candidates = generated.json()["candidates"]
        assert len(candidates) == 2
        assert len(external.image_calls) == 2
        assert all(
            DIARY_TEXT in call["json"]["prompt"] for call in external.image_calls
        )
        assert external.remote_requests == [
            {
                "method": "GET",
                "url": f"https://{REMOTE_IMAGE_IP}:443/generated.png",
                "host": "cdn.example",
                "sni_hostname": "cdn.example",
                "follow_redirects": False,
            }
        ]

        base64_image, remote_image = candidates
        kept = alice.put(
            f"/api/image/diary/{diary_id}/images",
            json={"keep_ids": [remote_image["id"]]},
        )
        assert kept.status_code == 200, kept.text
        assert [item["id"] for item in kept.json()["images"]] == [
            remote_image["id"]
        ]
        confirmed = alice.put(
            f"/api/diary/{diary_id}",
            json={"text": DIARY_TEXT, "draft_text": DIARY_TEXT, "status": "confirmed"},
        )
        assert confirmed.status_code == 200, confirmed.text

        first_publication = alice.put(
            f"/api/rooms/{room_id}/posts/diaries/{diary_id}",
            json={"image_ids": [remote_image["id"]]},
        )
        assert first_publication.status_code == 200, first_publication.text
        first_post = first_publication.json()
        assert first_post["snapshot"]["text"] == DIARY_TEXT
        assert first_post["media_urls"] == [remote_image["url"]]
        assert bob.get(remote_image["url"]).content == PNG_BYTES
        assert bob.get(base64_image["url"]).status_code == 404

        like_url = f"/api/rooms/{room_id}/posts/{first_post['id']}/like"
        assert bob.put(like_url).json() == {"liked": True, "like_count": 1}
        assert bob.put(like_url).json() == {"liked": True, "like_count": 1}
        comment_url = f"/api/rooms/{room_id}/posts/{first_post['id']}/comments"
        comment_payload = {"client_request_id": "journey-retry", "body": "真好"}
        first_comment = bob.post(comment_url, json=comment_payload)
        retried_comment = bob.post(
            comment_url,
            json={"client_request_id": "journey-retry", "body": "changed"},
        )
        assert first_comment.status_code == 201
        assert retried_comment.status_code == 200
        assert retried_comment.json() == first_comment.json()

        changed_text = "这是一段仍然只属于 Alice 的修改后日记。"
        changed = alice.put(
            f"/api/diary/{diary_id}", json={"text": changed_text}
        )
        assert changed.status_code == 200, changed.text
        partner_before_republish = bob.get(
            f"/api/rooms/{room_id}/feed"
        ).json()["items"][0]
        assert partner_before_republish["snapshot"]["text"] == DIARY_TEXT
        assert partner_before_republish["like_count"] == 1
        assert [item["body"] for item in partner_before_republish["comments"]] == [
            "真好"
        ]
        assert "source_id" not in partner_before_republish

        switched = alice.put(
            f"/api/image/diary/{diary_id}/images",
            json={"keep_ids": [base64_image["id"]]},
        )
        assert switched.status_code == 200, switched.text
        replacement = alice.put(
            f"/api/rooms/{room_id}/posts/diaries/{diary_id}",
            json={"image_ids": [base64_image["id"]]},
        )
        assert replacement.status_code == 200, replacement.text
        replacement_post = replacement.json()
        assert replacement_post["id"] != first_post["id"]
        assert replacement_post["snapshot"]["text"] == changed_text
        assert replacement_post["like_count"] == 0
        assert replacement_post["comments"] == []
        assert replacement_post["media_urls"] == [base64_image["url"]]
        assert bob.get(remote_image["url"]).status_code == 404
        assert bob.get(base64_image["url"]).content == PNG_BYTES
        assert bob.put(like_url).status_code == 404

        published_temperature = alice.put(
            f"/api/rooms/{room_id}/temperatures/{RECORD_DATE}"
        )
        assert published_temperature.status_code == 200, published_temperature.text
        assert published_temperature.json() == {
            "date": RECORD_DATE,
            "score": 72,
            "label": "温暖",
            "color": "#E89D7B",
            "nickname": "Alice",
        }
        bob_temperature = bob.get(
            f"/api/rooms/{room_id}/temperatures", params={"date": RECORD_DATE}
        )
        assert bob_temperature.status_code == 200
        assert bob_temperature.json()["partner"] == {
            "status": "available",
            "snapshot": published_temperature.json(),
        }
        assert "private" not in bob_temperature.text.lower()
        assert alice.delete(
            f"/api/rooms/{room_id}/temperatures/{RECORD_DATE}"
        ).status_code == 204
        assert bob.get(
            f"/api/rooms/{room_id}/temperatures", params={"date": RECORD_DATE}
        ).json()["partner"] == {"status": "unavailable"}

        assert alice.delete(
            f"/api/rooms/{room_id}/posts/{replacement_post['id']}"
        ).status_code == 204
        assert bob.get(f"/api/rooms/{room_id}/feed").json()["items"] == []
        assert bob.get(base64_image["url"]).status_code == 404
        assert alice.get(base64_image["url"]).content == PNG_BYTES

        final_note = alice.post(
            f"/api/rooms/{room_id}/posts/notes", json={"body": "before close"}
        )
        assert final_note.status_code == 201, final_note.text
        assert bob.get(f"/api/rooms/{room_id}/feed").json()["items"][0][
            "snapshot"
        ]["body"] == "before close"
        assert bob.post(f"/api/rooms/{room_id}/leave").status_code == 204

        for client in (alice, bob):
            assert client.get("/api/rooms/current").json() is None
            assert client.get(f"/api/rooms/{room_id}/feed").status_code == 404
            assert client.get(
                f"/api/rooms/{room_id}/temperatures", params={"date": RECORD_DATE}
            ).status_code == 404
            assert client.put(
                f"/api/rooms/{room_id}/posts/{final_note.json()['id']}/like"
            ).status_code == 404
        assert bob.get(remote_image["url"]).status_code == 404
        assert bob.get(base64_image["url"]).status_code == 404
        assert alice.get(remote_image["url"]).content == PNG_BYTES
        assert alice.get(base64_image["url"]).content == PNG_BYTES
        assert_private_source_is_hidden(
            bob, schedule.json()["id"], fragment.json()["id"], diary_id
        )
