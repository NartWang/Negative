import importlib
import sqlite3
from contextlib import contextmanager

import httpx
import pytest
from fastapi.testclient import TestClient


PASSWORD = "correct horse battery"
PNG_BYTES = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01"
    b"\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15\xc4\x89"
)
PNG_B64 = "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJ"
PNG_DATA_URL = f"data:image/png;base64,{PNG_B64}"


class QueuedAsyncClient:
    def __init__(self, outcomes, calls):
        self._outcomes = outcomes
        self._calls = calls

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):
        return None

    async def post(self, url, **kwargs):
        self._calls.append({"url": url, **kwargs})
        outcome = self._outcomes.pop(0)
        if isinstance(outcome, BaseException):
            raise outcome
        status_code, payload = outcome
        return httpx.Response(
            status_code,
            request=httpx.Request("POST", url),
            json=payload,
        )


@pytest.fixture
def ai_app(tmp_path, monkeypatch):
    db_path = tmp_path / "ai.sqlite3"
    upload_dir = tmp_path / "uploads"
    monkeypatch.setenv("ZHIJI_DB_PATH", str(db_path))
    monkeypatch.setenv("ZHIJI_UPLOAD_DIR", str(upload_dir))
    monkeypatch.setenv("FRONTEND_ORIGINS", "http://localhost:5173")
    monkeypatch.setenv("SESSION_COOKIE_SECURE", "false")
    monkeypatch.setenv("DIARY_API_BASE_URL", "")
    monkeypatch.setenv("DIARY_API_KEY", "")
    monkeypatch.setenv("IMAGE_API_BASE_URL", "")
    monkeypatch.setenv("IMAGE_API_KEY", "")

    import config
    import database
    import main
    import agents.diary_agent
    import agents.dual_timeline_agent
    import agents.image_agent
    import agents.nagging_transformer_agent
    import agents.weekly_comic_agent
    import routers.diary
    import routers.dual_timeline
    import routers.image
    import routers.transform
    import routers.weekly_comic

    importlib.reload(config)
    importlib.reload(database)
    diary_agent = importlib.reload(agents.diary_agent)
    image_agent = importlib.reload(agents.image_agent)
    weekly_agent = importlib.reload(agents.weekly_comic_agent)
    dual_agent = importlib.reload(agents.dual_timeline_agent)
    transform_agent = importlib.reload(agents.nagging_transformer_agent)
    diary_router = importlib.reload(routers.diary)
    image_router = importlib.reload(routers.image)
    weekly_router = importlib.reload(routers.weekly_comic)
    dual_router = importlib.reload(routers.dual_timeline)
    transform_router = importlib.reload(routers.transform)
    main = importlib.reload(main)
    return {
        "app": main.app,
        "db_path": db_path,
        "upload_dir": upload_dir,
        "diary_agent": diary_agent,
        "image_agent": image_agent,
        "weekly_agent": weekly_agent,
        "dual_agent": dual_agent,
        "transform_agent": transform_agent,
        "diary_router": diary_router,
        "image_router": image_router,
        "weekly_router": weekly_router,
        "dual_router": dual_router,
        "transform_router": transform_router,
    }


@contextmanager
def account(ai_app, username="ai-user"):
    with TestClient(
        ai_app["app"],
        base_url="http://testserver",
        raise_server_exceptions=False,
    ) as client:
        response = client.post(
            "/api/auth/register",
            json={
                "username": username,
                "password": PASSWORD,
                "nickname": "AI User",
            },
        )
        assert response.status_code == 201, response.text
        yield client, response.json()


def create_diary(client, *, text="diary text", draft_text=None):
    diary = client.post("/api/diary", json={"date": "2026-08-04"})
    assert diary.status_code == 200
    payload = {"text": text}
    if draft_text is not None:
        payload["draft_text"] = draft_text
    updated = client.put(f"/api/diary/{diary.json()['id']}", json=payload)
    assert updated.status_code == 200
    return updated.json()


def fetch_one(db_path, sql, params=()):
    with sqlite3.connect(db_path) as db:
        db.row_factory = sqlite3.Row
        row = db.execute(sql, params).fetchone()
    return dict(row) if row else None


def seed_pair(db_path, first_user_id, second_user_id):
    with sqlite3.connect(db_path) as db:
        db.execute(
            "INSERT INTO rooms (id, creator_user_id, status) "
            "VALUES ('ai-pair-room', ?, 'active')",
            (first_user_id,),
        )
        db.executemany(
            "INSERT INTO room_members (room_id, user_id, role, slot) "
            "VALUES ('ai-pair-room', ?, ?, ?)",
            [
                (first_user_id, "owner", 1),
                (second_user_id, "member", 2),
            ],
        )
        db.commit()


def assert_no_comic_mutation(ai_app):
    assert fetch_one(ai_app["db_path"], "SELECT id FROM weekly_comics") is None
    assert fetch_one(
        ai_app["db_path"], "SELECT id FROM dual_timeline_comics"
    ) is None
    assert fetch_one(ai_app["db_path"], "SELECT id FROM media_assets") is None
    assert not list(ai_app["upload_dir"].glob("*"))


def assert_no_generation_mutation(ai_app):
    for table in (
        "diaries",
        "images",
        "media_assets",
        "weekly_comics",
        "dual_timeline_comics",
        "room_posts",
    ):
        assert fetch_one(ai_app["db_path"], f"SELECT 1 FROM {table}") is None
    assert not list(ai_app["upload_dir"].glob("*"))


def weekly_generate(client):
    assert client.post(
        "/api/schedules",
        json={"date": "2026-08-04", "title": "weekly source"},
    ).status_code == 200
    return client.post(
        "/api/weekly-comic/generate",
        json={
            "week_start": "2026-08-04",
            "week_end": "2026-08-04",
            "style": "ghibli",
        },
    )


@contextmanager
def paired_account(ai_app, username):
    with TestClient(
        ai_app["app"],
        base_url="http://testserver",
        raise_server_exceptions=False,
    ) as alice, TestClient(
        ai_app["app"],
        base_url="http://testserver",
        raise_server_exceptions=False,
    ) as bob:
        alice_profile = alice.post(
            "/api/auth/register",
            json={
                "username": username,
                "password": PASSWORD,
                "nickname": "Alice",
            },
        ).json()
        bob_profile = bob.post(
            "/api/auth/register",
            json={
                "username": f"{username}-partner",
                "password": PASSWORD,
                "nickname": "Bob",
            },
        ).json()
        seed_pair(ai_app["db_path"], alice_profile["id"], bob_profile["id"])
        schedule = alice.post(
            "/api/schedules",
            json={"date": "2026-08-04", "title": "dual source"},
        )
        assert schedule.status_code == 200
        yield alice, [{"type": "schedule", "id": schedule.json()["id"]}]


def dual_generate(client, events):
    return client.post(
        "/api/dual-timeline/comic/generate",
        json={
            "date": "2026-08-04",
            "selected_a": events,
            "selected_b": [],
            "style": "ghibli",
        },
    )


def test_custom_prompts_never_interpolate_literal_none(ai_app):
    system_prompt, _ = ai_app["diary_agent"].build_diary_prompt(
        "2026-08-04", [], [], "custom", None
    )
    image_prompt = ai_app["image_agent"].build_image_prompt(
        "a quiet evening", "custom", None
    )

    assert "None" not in system_prompt
    assert "None" not in image_prompt


def test_missing_ai_configuration_returns_stable_service_errors(ai_app):
    with account(ai_app, "missing-config") as (client, _profile):
        assert client.post(
            "/api/schedules",
            json={"date": "2026-08-04", "title": "recorded day"},
        ).status_code == 200
        diary = create_diary(client)

        diary_response = client.post(
            f"/api/diary/{diary['id']}/ai-fill",
            json={"emotion_mode": "warm"},
        )
        image_response = client.post(
            f"/api/image/diary/{diary['id']}/images/batch",
            json={"style": "ghibli", "n": 1},
        )

    assert diary_response.status_code == 503
    assert diary_response.json() == {"detail": "AI service is not configured"}
    assert image_response.status_code == 503
    assert image_response.json() == {
        "detail": "image service is not configured"
    }


def test_empty_model_content_is_rejected_without_diary_mutation(
    ai_app, monkeypatch
):
    agent = ai_app["diary_agent"]
    agent.DIARY_API_BASE_URL = "https://ai.example/v1"
    agent.DIARY_API_KEY = "test-key"
    calls = []
    outcomes = [
        (
            200,
            {"choices": [{"message": {"content": "<think>only thought</think>"}}]},
        )
    ]
    monkeypatch.setattr(
        agent.httpx,
        "AsyncClient",
        lambda **_kwargs: QueuedAsyncClient(outcomes, calls),
    )

    with account(ai_app, "empty-content") as (client, profile):
        assert client.post(
            "/api/fragments",
            json={"date": "2026-08-04", "content": "source fragment"},
        ).status_code == 200
        diary = create_diary(client, text="manual text", draft_text="manual draft")
        before = fetch_one(
            ai_app["db_path"],
            "SELECT text, draft_text, source, emotion_mode FROM diaries "
            "WHERE id=? AND user_id=?",
            (diary["id"], profile["id"]),
        )

        response = client.post(
            f"/api/diary/{diary['id']}/ai-fill",
            json={"emotion_mode": "warm"},
        )
        after = fetch_one(
            ai_app["db_path"],
            "SELECT text, draft_text, source, emotion_mode FROM diaries "
            "WHERE id=? AND user_id=?",
            (diary["id"], profile["id"]),
        )

    assert response.status_code == 502
    assert response.json() == {"detail": "AI service returned empty content"}
    assert after == before
    assert len(calls) == 1


def test_diary_upstream_failure_has_stable_contract(ai_app, monkeypatch):
    agent = ai_app["diary_agent"]
    agent.DIARY_API_BASE_URL = "https://ai.example/v1"
    agent.DIARY_API_KEY = "test-key"
    calls = []
    outcomes = [httpx.ReadTimeout("upstream timeout")]
    monkeypatch.setattr(
        agent.httpx,
        "AsyncClient",
        lambda **_kwargs: QueuedAsyncClient(outcomes, calls),
    )

    with account(ai_app, "upstream-diary") as (client, _profile):
        assert client.post(
            "/api/schedules",
            json={"date": "2026-08-04", "title": "source schedule"},
        ).status_code == 200
        diary = create_diary(client)
        response = client.post(
            f"/api/diary/{diary['id']}/ai-fill",
            json={"emotion_mode": "real"},
        )

    assert response.status_code == 502
    assert response.json() == {
        "detail": "AI service is temporarily unavailable"
    }


@pytest.mark.asyncio
async def test_image_agent_preserves_base64_and_url_response_shapes(
    ai_app, monkeypatch
):
    agent = ai_app["image_agent"]
    agent.IMAGE_API_BASE_URL = "https://image.example/v1"
    agent.IMAGE_API_KEY = "test-key"
    calls = []
    outcomes = [
        (200, {"data": [{"b64_json": PNG_B64}]}),
        (200, {"data": [{"url": "https://cdn.example/image.png"}]}),
    ]
    monkeypatch.setattr(
        agent.httpx,
        "AsyncClient",
        lambda **_kwargs: QueuedAsyncClient(outcomes, calls),
    )

    sources = await agent.generate_batch(
        diary_text="latest text",
        paragraphs=[],
        style="ghibli",
        n=2,
    )

    assert sources == [PNG_DATA_URL, "https://cdn.example/image.png"]
    assert len(calls) == 2
    assert not list(ai_app["upload_dir"].glob("*"))


@pytest.mark.parametrize(
    "source",
    [PNG_DATA_URL, "https://cdn.example/generated.png"],
)
def test_base64_and_url_images_persist_as_protected_assets(
    ai_app, monkeypatch, source
):
    agent = ai_app["image_agent"]

    async def fake_generate_batch(**_kwargs):
        return [source]

    monkeypatch.setattr(agent, "generate_batch", fake_generate_batch)
    if source.startswith("https://"):
        from services import media_store

        async def fake_download_remote(_url):
            return PNG_BYTES, "image/png"

        monkeypatch.setattr(media_store, "download_remote", fake_download_remote)

    with account(ai_app, f"persist-{source.startswith('https')}") as (
        client,
        profile,
    ):
        diary = create_diary(client)
        response = client.post(
            f"/api/image/diary/{diary['id']}/images/batch",
            json={"style": "ghibli", "n": 1},
        )

    assert response.status_code == 200, response.text
    candidate = response.json()["candidates"][0]
    assert candidate["url"].startswith("/api/media/")
    asset = fetch_one(
        ai_app["db_path"],
        "SELECT owner_user_id, size_bytes FROM media_assets WHERE id=?",
        (candidate["asset_id"],),
    )
    assert asset == {"owner_user_id": profile["id"], "size_bytes": len(PNG_BYTES)}


def test_partial_image_api_batch_failure_leaves_no_database_or_files(
    ai_app, monkeypatch
):
    agent = ai_app["image_agent"]
    agent.IMAGE_API_BASE_URL = "https://image.example/v1"
    agent.IMAGE_API_KEY = "test-key"
    calls = []
    outcomes = [
        (200, {"data": [{"b64_json": PNG_B64}]}),
        httpx.ReadTimeout("second image timed out"),
    ]
    monkeypatch.setattr(
        agent.httpx,
        "AsyncClient",
        lambda **_kwargs: QueuedAsyncClient(outcomes, calls),
    )

    with account(ai_app, "partial-batch") as (client, _profile):
        diary = create_diary(client)
        response = client.post(
            f"/api/image/diary/{diary['id']}/images/batch",
            json={"style": "ghibli", "n": 2},
        )

    assert response.status_code == 502
    assert response.json() == {
        "detail": "image service is temporarily unavailable"
    }
    assert fetch_one(ai_app["db_path"], "SELECT id FROM media_assets") is None
    assert fetch_one(ai_app["db_path"], "SELECT id FROM images") is None
    assert not list(ai_app["upload_dir"].glob("*"))


def test_image_keep_selection_has_exact_set_semantics(ai_app, monkeypatch):
    agent = ai_app["image_agent"]

    async def fake_generate_batch(**_kwargs):
        return [PNG_DATA_URL, PNG_DATA_URL]

    monkeypatch.setattr(agent, "generate_batch", fake_generate_batch)

    with account(ai_app, "exact-keep") as (client, _profile):
        diary = create_diary(client)
        generated = client.post(
            f"/api/image/diary/{diary['id']}/images/batch",
            json={"style": "ghibli", "n": 2},
        )
        assert generated.status_code == 200
        ids = [item["id"] for item in generated.json()["candidates"]]

        both = client.put(
            f"/api/image/diary/{diary['id']}/images",
            json={"keep_ids": ids},
        )
        one = client.put(
            f"/api/image/diary/{diary['id']}/images",
            json={"keep_ids": ids[:1]},
        )
        none = client.put(
            f"/api/image/diary/{diary['id']}/images",
            json={"keep_ids": []},
        )

    assert [item["id"] for item in both.json()["images"]] == ids
    assert [item["id"] for item in one.json()["images"]] == ids[:1]
    assert none.json() == {"images": []}


def test_image_generation_uses_latest_persisted_diary_text(ai_app, monkeypatch):
    captured = []

    async def fake_generate_batch(**kwargs):
        captured.append(kwargs["diary_text"])
        return [PNG_DATA_URL]

    monkeypatch.setattr(ai_app["image_agent"], "generate_batch", fake_generate_batch)

    with account(ai_app, "latest-text") as (client, _profile):
        diary = create_diary(client, text="old", draft_text="old")
        saved = client.put(
            f"/api/diary/{diary['id']}",
            json={"text": "latest visible", "draft_text": "latest visible"},
        )
        assert saved.status_code == 200
        response = client.post(
            f"/api/image/diary/{diary['id']}/images/batch",
            json={"style": "ghibli", "n": 1},
        )

    assert response.status_code == 200
    assert captured == ["latest visible"]


def test_unknown_diary_update_is_404_and_letter_route_is_absent(ai_app):
    with account(ai_app, "removed-letter") as (client, _profile):
        update = client.put("/api/diary/999999", json={"text": "missing"})
        letter = client.post(
            "/api/letter/send",
            json={
                "webhook": "https://example.com/hook",
                "type": "test",
                "title": "test",
                "body": "test",
            },
        )

    assert update.status_code == 404
    assert update.json() == {"detail": "diary not found"}
    assert letter.status_code == 404


def test_weekly_comic_missing_planner_config_is_503_without_mutation(ai_app):
    with account(ai_app, "weekly-missing") as (client, _profile):
        response = weekly_generate(client)

    assert response.status_code == 503
    assert response.json() == {"detail": "AI service is not configured"}
    assert_no_comic_mutation(ai_app)


def test_dual_comic_missing_planner_config_is_503_without_mutation(ai_app):
    with paired_account(ai_app, "dual-missing") as (client, events):
        response = dual_generate(client, events)

    assert response.status_code == 503
    assert response.json() == {"detail": "AI service is not configured"}
    assert_no_comic_mutation(ai_app)


@pytest.mark.parametrize("kind", ["weekly", "dual"])
def test_comic_planner_upstream_failure_is_502_without_mutation(
    ai_app, monkeypatch, kind
):
    diary_agent = ai_app["diary_agent"]
    diary_agent.DIARY_API_BASE_URL = "https://ai.example/v1"
    diary_agent.DIARY_API_KEY = "test-key"
    ai_app["weekly_agent"].DIARY_API_BASE_URL = "https://ai.example/v1"
    ai_app["weekly_agent"].DIARY_API_KEY = "test-key"
    ai_app["dual_agent"].DIARY_API_BASE_URL = "https://ai.example/v1"
    ai_app["dual_agent"].DIARY_API_KEY = "test-key"
    calls = []
    outcomes = [httpx.ReadTimeout("planner timeout")]
    monkeypatch.setattr(
        diary_agent.httpx,
        "AsyncClient",
        lambda **_kwargs: QueuedAsyncClient(outcomes, calls),
    )

    if kind == "weekly":
        with account(ai_app, "weekly-planner-upstream") as (client, _profile):
            response = weekly_generate(client)
    else:
        with paired_account(ai_app, "dual-planner-upstream") as (client, events):
            response = dual_generate(client, events)

    assert response.status_code == 502
    assert response.json() == {
        "detail": "AI service is temporarily unavailable"
    }
    assert_no_comic_mutation(ai_app)


@pytest.mark.parametrize("kind", ["weekly", "dual"])
def test_comic_empty_planner_response_is_502_without_mutation(
    ai_app, monkeypatch, kind
):
    diary_agent = ai_app["diary_agent"]
    diary_agent.DIARY_API_BASE_URL = "https://ai.example/v1"
    diary_agent.DIARY_API_KEY = "test-key"
    ai_app["weekly_agent"].DIARY_API_BASE_URL = "https://ai.example/v1"
    ai_app["weekly_agent"].DIARY_API_KEY = "test-key"
    ai_app["dual_agent"].DIARY_API_BASE_URL = "https://ai.example/v1"
    ai_app["dual_agent"].DIARY_API_KEY = "test-key"
    calls = []
    outcomes = [
        (
            200,
            {"choices": [{"message": {"content": "<think>only thought</think>"}}]},
        )
    ]
    monkeypatch.setattr(
        diary_agent.httpx,
        "AsyncClient",
        lambda **_kwargs: QueuedAsyncClient(outcomes, calls),
    )

    if kind == "weekly":
        with account(ai_app, "weekly-planner-empty") as (client, _profile):
            response = weekly_generate(client)
    else:
        with paired_account(ai_app, "dual-planner-empty") as (client, events):
            response = dual_generate(client, events)

    assert response.status_code == 502
    assert response.json() == {"detail": "AI service returned empty content"}
    assert_no_comic_mutation(ai_app)


@pytest.mark.parametrize("kind", ["weekly", "dual"])
def test_comic_null_planner_prompt_is_502_without_literal_none(
    ai_app, monkeypatch, kind
):
    diary_agent = ai_app["diary_agent"]
    diary_agent.DIARY_API_BASE_URL = "https://ai.example/v1"
    diary_agent.DIARY_API_KEY = "test-key"
    calls = []
    outcomes = [
        (
            200,
            {
                "choices": [
                    {"message": {"content": '{"prompt":null,"caption":"x"}'}}
                ]
            },
        )
    ]
    monkeypatch.setattr(
        diary_agent.httpx,
        "AsyncClient",
        lambda **_kwargs: QueuedAsyncClient(outcomes, calls),
    )

    if kind == "weekly":
        with account(ai_app, "weekly-planner-null") as (client, _profile):
            response = weekly_generate(client)
    else:
        with paired_account(ai_app, "dual-planner-null") as (client, events):
            response = dual_generate(client, events)

    assert response.status_code == 502
    assert response.json() == {"detail": "AI service returned empty content"}
    assert_no_comic_mutation(ai_app)


@pytest.mark.parametrize("kind", ["weekly", "dual"])
def test_comic_image_upstream_failure_is_502_without_mutation(
    ai_app, monkeypatch, kind
):
    image_agent = ai_app["image_agent"]
    image_agent.IMAGE_API_BASE_URL = "https://image.example/v1"
    image_agent.IMAGE_API_KEY = "test-key"
    calls = []
    outcomes = [httpx.ReadTimeout("image timeout")]
    monkeypatch.setattr(
        image_agent.httpx,
        "AsyncClient",
        lambda **_kwargs: QueuedAsyncClient(outcomes, calls),
    )

    async def fake_plan_weekly(**_kwargs):
        return "weekly image prompt", "weekly caption"

    async def fake_plan_dual(**_kwargs):
        return "dual image prompt", "dual caption"

    monkeypatch.setattr(
        ai_app["weekly_router"], "plan_weekly_comic", fake_plan_weekly
    )
    monkeypatch.setattr(ai_app["dual_router"], "plan_comic", fake_plan_dual)

    if kind == "weekly":
        with account(ai_app, "weekly-image-upstream") as (client, _profile):
            response = weekly_generate(client)
    else:
        with paired_account(ai_app, "dual-image-upstream") as (client, events):
            response = dual_generate(client, events)

    assert response.status_code == 502
    assert response.json() == {
        "detail": "image service is temporarily unavailable"
    }
    assert_no_comic_mutation(ai_app)


def transform_request(client):
    return client.post(
        "/api/transform/nagging/transform",
        json={"nag_text": "早点睡，别再熬夜了", "relation": "妈妈"},
    )


def configure_transform_transport(ai_app, monkeypatch, outcomes):
    diary_agent = ai_app["diary_agent"]
    diary_agent.DIARY_API_BASE_URL = "https://ai.example/v1"
    diary_agent.DIARY_API_KEY = "test-key"
    calls = []
    monkeypatch.setattr(
        diary_agent.httpx,
        "AsyncClient",
        lambda **_kwargs: QueuedAsyncClient(outcomes, calls),
    )
    return calls


def test_transform_missing_config_is_stable_503(ai_app):
    with account(ai_app, "transform-missing") as (client, _profile):
        response = transform_request(client)

    assert response.status_code == 503
    assert response.json() == {"detail": "AI service is not configured"}
    assert_no_generation_mutation(ai_app)


def test_transform_http_failure_is_stable_502(ai_app, monkeypatch):
    configure_transform_transport(
        ai_app, monkeypatch, [httpx.ReadTimeout("provider timed out")]
    )

    with account(ai_app, "transform-upstream") as (client, _profile):
        response = transform_request(client)

    assert response.status_code == 502
    assert response.json() == {
        "detail": "AI service is temporarily unavailable"
    }
    assert_no_generation_mutation(ai_app)


def test_transform_invalid_json_never_echoes_raw_model_output(
    ai_app, monkeypatch
):
    sentinel = "MODEL_SECRET_SENTINEL_9f2d"
    configure_transform_transport(
        ai_app,
        monkeypatch,
        [(200, {"choices": [{"message": {"content": f"not json {sentinel}"}}]})],
    )

    with account(ai_app, "transform-invalid-json") as (client, _profile):
        response = transform_request(client)

    assert response.status_code == 502
    assert response.json() == {
        "detail": "AI service returned an invalid response"
    }
    assert sentinel not in response.text
    assert_no_generation_mutation(ai_app)


def test_transform_missing_fields_is_stable_502(ai_app, monkeypatch):
    configure_transform_transport(
        ai_app,
        monkeypatch,
        [
            (
                200,
                {
                    "choices": [
                        {
                            "message": {
                                "content": '{"help_request":"知道啦"}'
                            }
                        }
                    ]
                },
            )
        ],
    )

    with account(ai_app, "transform-missing-fields") as (client, _profile):
        response = transform_request(client)

    assert response.status_code == 502
    assert response.json() == {
        "detail": "AI service returned an invalid response"
    }
    assert_no_generation_mutation(ai_app)


def test_transform_empty_output_is_stable_502(ai_app, monkeypatch):
    sentinel = "HIDDEN_REASONING_SENTINEL_7ac1"
    configure_transform_transport(
        ai_app,
        monkeypatch,
        [
            (
                200,
                {
                    "choices": [
                        {
                            "message": {
                                "content": f"<think>{sentinel}</think>"
                            }
                        }
                    ]
                },
            )
        ],
    )

    with account(ai_app, "transform-empty") as (client, _profile):
        response = transform_request(client)

    assert response.status_code == 502
    assert response.json() == {"detail": "AI service returned empty content"}
    assert sentinel not in response.text
    assert_no_generation_mutation(ai_app)
