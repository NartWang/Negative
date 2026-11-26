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
    monkeypatch.delenv("IMAGE_API_KEYS", raising=False)

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


def test_image_api_keys_environment_supports_pool_without_legacy(monkeypatch):
    import config

    with monkeypatch.context() as env:
        env.setenv("IMAGE_API_KEYS", " pool-alpha, pool-beta, pool-alpha, ,pool-gamma ")
        env.delenv("IMAGE_API_KEY", raising=False)
        reloaded = importlib.reload(config)

        assert reloaded.IMAGE_API_KEY == ""
        assert reloaded.IMAGE_API_KEYS == (
            "pool-alpha",
            "pool-beta",
            "pool-gamma",
        )

    importlib.reload(config)


def test_parse_image_api_keys_uses_legacy_fallback_and_stable_deduplication():
    from config import parse_image_api_keys

    assert parse_image_api_keys(None, " legacy-placeholder ") == (
        "legacy-placeholder",
    )
    assert parse_image_api_keys(" , ", " legacy-placeholder ") == (
        "legacy-placeholder",
    )
    assert parse_image_api_keys(" first,second,first, third,second ", "legacy") == (
        "first",
        "second",
        "third",
    )


def test_image_agent_page_keys_are_stable_and_rotate(monkeypatch):
    import agents.image_agent as image_agent

    nine_keys = tuple(f"pool-{index}" for index in range(9))
    monkeypatch.setattr(image_agent, "IMAGE_API_KEYS", nine_keys, raising=False)
    monkeypatch.setattr(image_agent, "IMAGE_API_KEY", "legacy-placeholder")

    assert [image_agent.image_api_key_for_page(index) for index in range(9)] == list(
        nine_keys
    )

    monkeypatch.setattr(
        image_agent,
        "IMAGE_API_KEYS",
        ("pool-one", "pool-two", "pool-three"),
    )

    assert image_agent.configured_image_api_keys() == (
        "pool-one",
        "pool-two",
        "pool-three",
    )
    assert image_agent.primary_image_api_key() == "pool-one"
    assert [image_agent.image_api_key_for_page(index) for index in range(9)] == [
        "pool-one",
        "pool-two",
        "pool-three",
        "pool-one",
        "pool-two",
        "pool-three",
        "pool-one",
        "pool-two",
        "pool-three",
    ]


def test_image_agent_dynamic_legacy_fallback_and_pool_only_configuration(monkeypatch):
    import agents.image_agent as image_agent

    monkeypatch.setattr(image_agent, "IMAGE_API_BASE_URL", "https://image.example/v1")
    monkeypatch.setattr(image_agent, "IMAGE_MODEL", "image-model-placeholder")
    monkeypatch.setattr(image_agent, "IMAGE_API_KEYS", (), raising=False)
    monkeypatch.setattr(image_agent, "IMAGE_API_KEY", "runtime-legacy-placeholder")

    assert image_agent.configured_image_api_keys() == (
        "runtime-legacy-placeholder",
    )
    image_agent._require_image_configuration()

    monkeypatch.setattr(image_agent, "IMAGE_API_KEYS", ("pool-only-placeholder",))
    monkeypatch.setattr(image_agent, "IMAGE_API_KEY", "")

    assert image_agent.primary_image_api_key() == "pool-only-placeholder"
    image_agent._require_image_configuration()


@pytest.mark.asyncio
async def test_image_requests_use_selected_key_without_leaking_it(monkeypatch):
    import agents.image_agent as image_agent

    selected_key = "selected-sensitive-placeholder"
    calls = []
    outcomes = [
        (200, {"data": [{"b64_json": PNG_B64}]}),
        (200, {"data": [{"b64_json": PNG_B64}]}),
    ]
    client = QueuedAsyncClient(outcomes, calls)

    assert await image_agent._request_image(
        client,
        "page prompt",
        api_key=selected_key,
    ) == PNG_DATA_URL
    assert await image_agent._request_reference_image(
        client,
        "page prompt",
        PNG_BYTES,
        "image/png",
        api_key=selected_key,
    ) == PNG_DATA_URL
    assert [call["headers"]["Authorization"] for call in calls] == [
        f"Bearer {selected_key}",
        f"Bearer {selected_key}",
    ]

    failing_client = QueuedAsyncClient(
        [httpx.ReadTimeout(selected_key)],
        [],
    )
    with pytest.raises(image_agent.ImageUpstreamError) as caught:
        await image_agent._request_image(
            failing_client,
            "page prompt",
            api_key=selected_key,
        )
    assert selected_key not in str(caught.value)
    assert selected_key not in repr(caught.value.__cause__)


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


def test_upload_describes_photo_only_when_explicitly_requested(ai_app, monkeypatch):
    calls = []

    async def fake_describe_photo(content, extension):
        calls.append((content, extension))
        return "a private diary moment"

    monkeypatch.setattr(
        ai_app["diary_agent"],
        "describe_photo",
        fake_describe_photo,
    )

    with account(ai_app, "upload-description-boundary") as (client, _profile):
        stored_only = client.post(
            "/api/upload",
            files={"file": ("avatar.png", PNG_BYTES, "image/png")},
        )
        described = client.post(
            "/api/upload?describe=true",
            files={"file": ("diary-fragment.png", PNG_BYTES, "image/png")},
        )

    assert stored_only.status_code == described.status_code == 200
    assert stored_only.json()["photo_description"] is None
    assert described.json()["photo_description"] == "a private diary moment"
    assert calls == [(PNG_BYTES, ".png")]


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
            "style": "watercolor",
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
            "style": "watercolor",
        },
    )


def test_custom_image_prompt_never_interpolates_literal_none(ai_app):
    image_prompt = ai_app["image_agent"].build_image_prompt(
        "a quiet evening", "custom", None
    )

    assert "None" not in image_prompt


def test_diary_model_defaults_and_vision_fallback(monkeypatch):
    import dotenv
    import config

    with monkeypatch.context() as env:
        env.setattr(dotenv, "load_dotenv", lambda: False)
        env.delenv("DIARY_MODEL", raising=False)
        env.delenv("VISION_MODEL", raising=False)
        reloaded = importlib.reload(config)
        assert reloaded.DIARY_MODEL == "claude-opus-4-6"
        assert reloaded.VISION_MODEL == "claude-opus-4-6"

        env.setenv("DIARY_MODEL", "diary-override")
        env.delenv("VISION_MODEL", raising=False)
        reloaded = importlib.reload(config)
        assert reloaded.DIARY_MODEL == "diary-override"
        assert reloaded.VISION_MODEL == "diary-override"

        env.setenv("VISION_MODEL", "vision-override")
        reloaded = importlib.reload(config)
        assert reloaded.VISION_MODEL == "vision-override"

    importlib.reload(config)


def test_diary_prompt_loads_template_and_separates_input_groups():
    from agents.diary_agent import build_diary_prompt

    prompt = build_diary_prompt(
        text="今天项目讨论结束了。",
        fragments=[
            {
                "content": "下班时云很低",
                "mood_tag": "平静",
                "photo_description": "窗外是低垂的灰色云层",
            },
            {"content": None, "photo_description": "桌上放着一杯咖啡"},
            {"content": None, "mood_tag": "低落"},
        ],
        allow_imaginative=True,
    )

    assert prompt.startswith('你是"日记编辑器"。')
    assert "{{" not in prompt
    assert "【用户文本】\n今天项目讨论结束了。" in prompt
    assert "【日程】" not in prompt
    assert "【是否接受新增意象】\ntrue" in prompt

    fragment_section = prompt.split("【随手记】", 1)[1].split(
        "【照片描述】", 1
    )[0]
    photo_section = prompt.split("【照片描述】", 1)[1].split(
        "【是否接受新增意象】", 1
    )[0]
    assert "下班时云很低" in fragment_section
    assert "平静" not in prompt
    assert "低落" not in prompt
    assert "（无文字）" not in prompt
    assert "窗外是低垂的灰色云层" not in fragment_section
    assert "窗外是低垂的灰色云层" in photo_section
    assert "桌上放着一杯咖啡" in photo_section


def test_real_diary_prompt_preserves_facts_without_schedule_rules():
    from agents.diary_agent import build_diary_prompt

    prompt = build_diary_prompt(
        text="今天很忙。",
        fragments=[],
        allow_imaginative=False,
    )

    assert "不改变核心事实、人物关系和时间线" in prompt
    assert "禁止改变原始输入中的核心事实" in prompt
    assert "schedules" not in prompt
    assert "日程" not in prompt
    for hallucinated_fact in ("早上醒来", "跑了三公里", "冲了个澡"):
        assert hallucinated_fact not in prompt


def test_diary_prompt_uses_v3_formal_rules_without_examples_or_type_section():
    from agents.diary_agent import build_diary_prompt

    prompt = build_diary_prompt(
        text="",
        fragments=[],
        allow_imaginative=False,
    )

    assert "输出不少于用户输入的总字数，只做整合和润色，不做压缩" in prompt
    assert "输入少于30字且已经是完整表达时，原样返回，不扩写不补充" in prompt
    assert "每段最多一处意象操作" in prompt
    assert "活人感写作规则" in prompt
    assert "优先级：text > fragments > photos" in prompt
    assert "当 text 为空或缺失时，以 fragments 为叙事主干" in prompt
    assert "四、输入类型处理方式" not in prompt
    assert "输出示例" not in prompt


def test_picturebook_source_prompt_preserves_length_factuality_and_mode_mapping():
    from agents.diary_agent import build_picturebook_source_prompt

    real_prompt = build_picturebook_source_prompt(
        text="只选择这一小段。",
        allow_imaginative=False,
    )
    imagery_prompt = build_picturebook_source_prompt(
        text="云贴着山脊慢慢走。",
        allow_imaginative=True,
    )

    assert "450–550字" in real_prompt
    assert "事实准确性优先于篇幅" in real_prompt
    assert "最长的、事实支持的版本" in real_prompt
    assert "【用户确认后的日记】\n只选择这一小段。" in real_prompt
    assert "【用户之前选择的意象选项】\nfalse" in real_prompt
    assert "【用户之前选择的意象选项】\ntrue" in imagery_prompt
    assert "{{text}}" not in real_prompt
    assert "{{allow_imaginative}}" not in real_prompt


def test_picturebook_source_prompt_examples_omit_known_invented_events():
    from agents.diary_agent import load_picturebook_source_prompt

    prompt = load_picturebook_source_prompt()

    for invented_event in (
        "早上醒来",
        "冲了个澡",
        "那班地铁",
        "办公室里很安静",
        "棘手的问题",
    ):
        assert invented_event not in prompt


@pytest.mark.asyncio
async def test_picturebook_adapter_uses_diary_credentials_model_and_selected_text(
    ai_app, monkeypatch
):
    agent = ai_app["diary_agent"]
    agent.DIARY_API_BASE_URL = "https://ai.example/v1"
    agent.DIARY_API_KEY = "test-key"
    agent.DIARY_MODEL = "diary-test-model"
    calls = []
    outcomes = [(200, {"choices": [{"message": {"content": "扩写后的日记"}}]})]
    monkeypatch.setattr(
        agent.httpx,
        "AsyncClient",
        lambda **_kwargs: QueuedAsyncClient(outcomes, calls),
    )

    result = await agent.adapt_for_picturebook(
        "用户选中的不可变文本",
        allow_imaginative=True,
    )

    assert result == "扩写后的日记"
    assert calls[0]["headers"] == {"Authorization": "Bearer test-key"}
    assert calls[0]["json"]["model"] == "diary-test-model"
    assert (
        "【用户确认后的日记】\n用户选中的不可变文本"
        in calls[0]["json"]["messages"][0]["content"]
    )


@pytest.mark.asyncio
async def test_generate_diary_uses_diary_credentials_and_model(ai_app, monkeypatch):
    agent = ai_app["diary_agent"]
    agent.DIARY_API_BASE_URL = "https://ai.example/v1"
    agent.DIARY_API_KEY = "test-key"
    agent.DIARY_MODEL = "diary-test-model"
    calls = []
    outcomes = [(200, {"choices": [{"message": {"content": "生成的日记"}}]})]
    monkeypatch.setattr(
        agent.httpx,
        "AsyncClient",
        lambda **_kwargs: QueuedAsyncClient(outcomes, calls),
    )

    result = await agent.generate_diary(
        text="原始文本",
        fragments=[],
        allow_imaginative=False,
    )

    assert result == "生成的日记"
    assert calls[0]["headers"] == {"Authorization": "Bearer test-key"}
    assert calls[0]["json"]["model"] == "diary-test-model"
    assert calls[0]["json"]["max_tokens"] == 800
    assert "【用户文本】\n原始文本" in calls[0]["json"]["messages"][0]["content"]


@pytest.mark.asyncio
async def test_generate_diary_scales_and_caps_output_token_budget(
    ai_app, monkeypatch
):
    agent = ai_app["diary_agent"]
    agent.DIARY_API_BASE_URL = "https://ai.example/v1"
    agent.DIARY_API_KEY = "test-key"
    calls = []
    outcomes = [
        (
            200,
            {
                "choices": [
                    {
                        "message": {"content": "中等长度日记"},
                        "finish_reason": "stop",
                    }
                ]
            },
        ),
        (
            200,
            {
                "choices": [
                    {
                        "message": {"content": "最大长度日记"},
                        "finish_reason": "stop",
                    }
                ]
            },
        ),
    ]
    monkeypatch.setattr(
        agent.httpx,
        "AsyncClient",
        lambda **_kwargs: QueuedAsyncClient(outcomes, calls),
    )

    await agent.generate_diary(
        text="文" * 500,
        fragments=[
            {"content": "随" * 400, "photo_description": "图" * 400}
        ],
        allow_imaginative=False,
    )
    await agent.generate_diary(
        text="文" * 4000,
        fragments=[],
        allow_imaginative=False,
    )

    medium_budget = calls[0]["json"]["max_tokens"]
    assert 800 < medium_budget < 4096
    assert calls[1]["json"]["max_tokens"] == 4096


def test_missing_ai_configuration_returns_stable_service_errors(ai_app):
    with account(ai_app, "missing-config") as (client, _profile):
        assert client.post(
            "/api/fragments",
            json={"date": "2026-08-04", "content": "recorded day"},
        ).status_code == 200
        diary = create_diary(client)

        diary_response = client.post(
            f"/api/diary/{diary['id']}/ai-fill",
            json={"emotion_mode": "imagery"},
        )
        image_response = client.post(
            f"/api/image/diary/{diary['id']}/images/batch",
            json={"style": "watercolor"},
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
            json={"emotion_mode": "imagery"},
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


def test_truncated_diary_response_is_rejected_without_mutation(
    ai_app, monkeypatch
):
    agent = ai_app["diary_agent"]
    agent.DIARY_API_BASE_URL = "https://ai.example/v1"
    agent.DIARY_API_KEY = "test-key"
    calls = []
    outcomes = [
        (
            200,
            {
                "choices": [
                    {
                        "message": {"content": "这是一段被截断的日记"},
                        "finish_reason": "length",
                    }
                ]
            },
        )
    ]
    monkeypatch.setattr(
        agent.httpx,
        "AsyncClient",
        lambda **_kwargs: QueuedAsyncClient(outcomes, calls),
    )

    with account(ai_app, "truncated-content") as (client, profile):
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
            json={"emotion_mode": "imagery"},
        )
        after = fetch_one(
            ai_app["db_path"],
            "SELECT text, draft_text, source, emotion_mode FROM diaries "
            "WHERE id=? AND user_id=?",
            (diary["id"], profile["id"]),
        )

    assert response.status_code == 502
    assert response.json() == {"detail": "AI service returned an invalid response"}
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
            "/api/fragments",
            json={"date": "2026-08-04", "content": "source fragment"},
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

    sources = [
        (
            await agent.generate_batch(
                diary_text="latest text",
                paragraphs=[],
                style="watercolor",
            )
        )[0]
        for _ in range(2)
    ]

    # One illustration per request; both upstream response shapes stay supported.
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
            json={"style": "watercolor"},
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


def test_image_api_failure_leaves_no_database_or_files(
    ai_app, monkeypatch
):
    agent = ai_app["image_agent"]
    agent.IMAGE_API_BASE_URL = "https://image.example/v1"
    agent.IMAGE_API_KEY = "test-key"
    calls = []
    outcomes = [httpx.ReadTimeout("image timed out")]
    monkeypatch.setattr(
        agent.httpx,
        "AsyncClient",
        lambda **_kwargs: QueuedAsyncClient(outcomes, calls),
    )

    with account(ai_app, "partial-batch") as (client, _profile):
        diary = create_diary(client)
        response = client.post(
            f"/api/image/diary/{diary['id']}/images/batch",
            json={"style": "watercolor"},
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
            json={"style": "watercolor"},
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
            json={"style": "watercolor"},
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
