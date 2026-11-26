import json

import pytest


SNAPSHOTS = [
    {
        "id": 11,
        "date": "2026-08-01",
        "status": "confirmed",
        "body": "上午整理旧照片，晚上给妈妈打电话。",
    },
    {
        "id": 12,
        "date": "2026-08-03",
        "status": "confirmed",
        "body": "加班到很晚，但路上买到了喜欢的热牛奶。",
    },
]


@pytest.mark.asyncio
async def test_storyline_candidates_strip_reasoning_and_validate_grounded_contract(
    monkeypatch,
):
    from agents import time_story_agent

    calls = []

    async def fake_completion(**kwargs):
        calls.append(kwargs)
        return """<think>private reasoning</think>
```json
{
  "items": [
    {
      "id": "quiet-care",
      "title": "被照亮的小照顾",
      "summary": "旧照片、电话和热牛奶串成一条温柔线索。",
      "source_dates": ["2026-08-01", "2026-08-03"]
    },
    {
      "id": "late-night",
      "title": "晚归路上的一点热",
      "summary": "加班后的热牛奶成为疲惫里的停靠点。",
      "source_dates": ["2026-08-03"]
    },
    {
      "id": "family-thread",
      "title": "电话另一端",
      "summary": "整理照片和打电话让家人的存在重新清晰。",
      "source_dates": ["2026-08-01"]
    }
  ]
}
```"""

    monkeypatch.setattr(time_story_agent, "request_chat_completion", fake_completion)

    result = await time_story_agent.generate_storyline_candidates(SNAPSHOTS)

    assert [item.id for item in result.items] == [
        "quiet-care",
        "late-night",
        "family-thread",
    ]
    assert result.items[0].source_dates == ["2026-08-01", "2026-08-03"]
    assert len(calls) == 1
    call = calls[0]
    assert call["timeout"] == 45
    assert call["temperature"] == 0.3
    assert call["max_tokens"] == 1200
    encoded_messages = json.dumps(call["messages"], ensure_ascii=False)
    assert "JSON only" in encoded_messages
    assert "不得虚构事实" in encoded_messages
    assert "2026-08-01 | confirmed | 上午整理旧照片" in encoded_messages
    assert encoded_messages.index("2026-08-01") < encoded_messages.index("2026-08-03")


@pytest.mark.asyncio
async def test_storyline_candidates_reject_malformed_duplicate_and_ungrounded_dates(
    monkeypatch,
):
    from agents import time_story_agent

    async def fake_completion(**_kwargs):
        return json.dumps(
            {
                "items": [
                    {
                        "id": "same",
                        "title": "A",
                        "summary": "A",
                        "source_dates": ["2026-08-01"],
                    },
                    {
                        "id": "same",
                        "title": "B",
                        "summary": "B",
                        "source_dates": ["2026-08-02"],
                    },
                    {
                        "id": "future",
                        "title": "C",
                        "summary": "C",
                        "source_dates": ["2026-09-01"],
                    },
                ]
            },
            ensure_ascii=False,
        )

    monkeypatch.setattr(time_story_agent, "request_chat_completion", fake_completion)

    with pytest.raises(time_story_agent.TimeStoryAIContractError) as exc:
        await time_story_agent.generate_storyline_candidates(SNAPSHOTS)

    assert str(exc.value) == "time story AI response failed contract"


@pytest.mark.asyncio
async def test_storyline_candidates_reject_overlong_fields(monkeypatch):
    from agents import time_story_agent

    async def fake_completion(**_kwargs):
        return json.dumps(
            {
                "items": [
                    {
                        "id": "x" * 41,
                        "title": "A",
                        "summary": "A",
                        "source_dates": ["2026-08-01"],
                    },
                    {
                        "id": "b",
                        "title": "B",
                        "summary": "B",
                        "source_dates": ["2026-08-03"],
                    },
                    {
                        "id": "c",
                        "title": "C",
                        "summary": "C",
                        "source_dates": ["2026-08-01"],
                    },
                ]
            },
            ensure_ascii=False,
        )

    monkeypatch.setattr(time_story_agent, "request_chat_completion", fake_completion)

    with pytest.raises(time_story_agent.TimeStoryAIContractError):
        await time_story_agent.generate_storyline_candidates(SNAPSHOTS)


@pytest.mark.asyncio
async def test_narrative_prompt_uses_selected_storyline_and_same_snapshots(monkeypatch):
    from agents import time_story_agent

    calls = []

    async def fake_completion(**kwargs):
        calls.append(kwargs)
        return "这是一篇只根据所选线索写出的长故事。"

    monkeypatch.setattr(time_story_agent, "request_chat_completion", fake_completion)
    candidate = time_story_agent.StorylineCandidate(
        id="quiet-care",
        title="被照亮的小照顾",
        summary="旧照片、电话和热牛奶串成一条温柔线索。",
        source_dates=["2026-08-01", "2026-08-03"],
    )

    narrative = await time_story_agent.generate_time_story_narrative(
        SNAPSHOTS,
        candidate,
    )

    assert narrative == "这是一篇只根据所选线索写出的长故事。"
    call = calls[0]
    assert call["timeout"] == 60
    assert call["temperature"] == 0.5
    assert call["max_tokens"] == 2400
    encoded_messages = json.dumps(call["messages"], ensure_ascii=False)
    assert "被照亮的小照顾" in encoded_messages
    assert "旧照片、电话和热牛奶" in encoded_messages
    assert "2026-08-01 | confirmed | 上午整理旧照片" in encoded_messages
    assert "2026-08-03 | confirmed | 加班到很晚" in encoded_messages


@pytest.mark.asyncio
async def test_narrative_output_is_capped_to_contract_limit(monkeypatch):
    from agents import time_story_agent

    async def fake_completion(**_kwargs):
        return "长" * 12050

    monkeypatch.setattr(time_story_agent, "request_chat_completion", fake_completion)
    candidate = time_story_agent.StorylineCandidate(
        id="quiet-care",
        title="被照亮的小照顾",
        summary="旧照片、电话和热牛奶串成一条温柔线索。",
        source_dates=["2026-08-01"],
    )

    narrative = await time_story_agent.generate_time_story_narrative(
        SNAPSHOTS,
        candidate,
    )

    assert len(narrative) == 12000
