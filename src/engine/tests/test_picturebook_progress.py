"""绘本逐页进度:每张图渲染完就立即持久化,不等整批 gather 完成。

规格 5.3:ready_pages 只统计已持久化且媒体记录完整的 ready 页;重试保留已
完成页。当前实现用 asyncio.gather 等所有图完成才落库,这些测试先把它们卡红。
"""

from __future__ import annotations

import asyncio

import pytest

from tests.test_story_workflow import (
    PNG_DATA_URL,
    create_account,
    fetch_all,
    fetch_one,
    insert_picturebook_render_pages,
)


@pytest.mark.asyncio
async def test_each_completed_page_persists_before_others_finish(db, monkeypatch):
    import routers.picturebook as picturebook_router

    job_id = await insert_picturebook_render_pages(db, user_id=42, page_count=3)
    # 3 页各自一个 future:先完成第 2 页,其余挂起。
    futures = {
        index: asyncio.get_running_loop().create_future() for index in range(3)
    }

    async def fake_generate_page_image(prompt, character, api_key=None):
        index = int(prompt.removeprefix("prompt-"))
        return await futures[index]

    monkeypatch.setattr(
        picturebook_router, "generate_page_image", fake_generate_page_image
    )

    render = asyncio.create_task(
        picturebook_router._render_pending_pages(db, job_id, 42, None)
    )
    try:
        # 给事件循环一拍,让所有渲染协程都进入等待。
        await asyncio.sleep(0.05)
        futures[2].set_result(PNG_DATA_URL)

        # 页 2 必须在页 0/1 完成之前就持久化为 ready。
        for _ in range(100):
            row = await fetch_one(
                db,
                "SELECT status FROM picturebook_pages "
                "WHERE job_id=? AND page_index=2",
                (job_id,),
            )
            if row["status"] == "ready":
                break
            await asyncio.sleep(0.01)
        else:
            raise AssertionError("page 2 was not persisted while others pending")

        assert not futures[0].done()
        assert not futures[1].done()
        ready = await fetch_all(
            db,
            "SELECT page_index, status FROM picturebook_pages "
            "WHERE job_id=? AND status='ready'",
            (job_id,),
        )
        assert [row["page_index"] for row in ready] == [2]
    finally:
        for future in futures.values():
            if not future.done():
                future.cancel()
        render.cancel()
        await asyncio.gather(render, return_exceptions=True)


@pytest.mark.asyncio
async def test_retry_only_rerenders_failed_pages(db, monkeypatch):
    import routers.picturebook as picturebook_router

    job_id = await insert_picturebook_render_pages(db, user_id=43, page_count=3)

    async def first_pass(prompt, character, api_key=None):
        index = int(prompt.removeprefix("prompt-"))
        if index == 1:
            raise picturebook_router.GenerationServiceError("temporary failure")
        return PNG_DATA_URL

    monkeypatch.setattr(
        picturebook_router, "generate_page_image", first_pass
    )
    assert await picturebook_router._render_pending_pages(db, job_id, 43, None) == 1

    ready_assets = await fetch_all(
        db,
        "SELECT page_index, asset_id FROM picturebook_pages "
        "WHERE job_id=? AND status='ready' ORDER BY page_index",
        (job_id,),
    )
    assert [row["page_index"] for row in ready_assets] == [0, 2]

    retried = []

    async def retry_pass(prompt, character, api_key=None):
        retried.append(int(prompt.removeprefix("prompt-")))
        return PNG_DATA_URL

    monkeypatch.setattr(
        picturebook_router, "generate_page_image", retry_pass
    )
    assert await picturebook_router._render_pending_pages(db, job_id, 43, None) == 0
    assert retried == [1]

    # 已完成页的资产未被重写。
    after = await fetch_all(
        db,
        "SELECT page_index, asset_id FROM picturebook_pages "
        "WHERE job_id=? AND page_index IN (0, 2) ORDER BY page_index",
        (job_id,),
    )
    assert [row["asset_id"] for row in after] == [
        row["asset_id"] for row in ready_assets
    ]
