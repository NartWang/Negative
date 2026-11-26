"""底片夹 PDF 导出:可用性、按日组合、时光故事与所有权。"""

from __future__ import annotations

import sqlite3

import pytest
from fastapi.testclient import TestClient

from tests.test_film_folder import (
    PASSWORD,
    film_app,
    seed_completed_work_book,
    two_clients,
)


def _seed_day(db_path, user_id, *, date="2026-08-08", with_diary=True,
              with_book=True):
    diary_id = None
    if with_diary:
        with sqlite3.connect(db_path) as db:
            cursor = db.execute(
                "INSERT INTO diaries (date, text, status, user_id) "
                "VALUES (?, '今天的正文。', 'confirmed', ?)",
                (date, user_id),
            )
            diary_id = cursor.lastrowid
            db.commit()
    if with_book:
        with sqlite3.connect(db_path) as db:
            cursor = db.execute(
                "INSERT INTO picturebook_jobs (user_id, diary_id, style, status, "
                "stage, total_pages, created_at, updated_at) "
                "VALUES (?, ?, 'watercolor', 'done', 'done', 9, 't', ?)",
                (user_id, diary_id, f"{date}T12:00:00Z"),
            )
            job_id = cursor.lastrowid
            for index in range(9):
                db.execute(
                    "INSERT INTO picturebook_pages (job_id, page_index, image_id, "
                    "caption, status, image_url, created_at, updated_at) "
                    "VALUES (?, ?, ?, ?, 'ready', ?, 't', 't')",
                    (job_id, index, f"p{index}", f"cap{index}",
                     f"/api/upload/missing-{date}-{index}.png"),
                )
            db.commit()


def test_day_availability(film_app):
    app, db_path = film_app
    with two_clients(app, db_path) as ((alice, alice_id), _):
        _seed_day(db_path, alice_id, with_diary=True, with_book=True)
        payload = alice.get("/api/export/day/2026-08-08/availability")
        assert payload.status_code == 200
        assert payload.json() == {"has_diary": True, "has_picturebooks": True}

        _seed_day(db_path, alice_id, date="2026-08-07", with_diary=True, with_book=False)
        payload = alice.get("/api/export/day/2026-08-07/availability").json()
        assert payload == {"has_diary": True, "has_picturebooks": False}

        payload = alice.get("/api/export/day/2026-08-06/availability").json()
        assert payload == {"has_diary": False, "has_picturebooks": False}


def test_day_pdf_selection_combinations(film_app):
    app, db_path = film_app
    with two_clients(app, db_path) as ((alice, alice_id), _):
        _seed_day(db_path, alice_id)

        diary_only = alice.post(
            "/api/export/day/2026-08-08/pdf",
            json={"include_diary": True, "include_picturebooks": False},
        )
        assert diary_only.status_code == 200
        assert "%PDF" in diary_only.content[:8].decode("latin1")

        book_only = alice.post(
            "/api/export/day/2026-08-08/pdf",
            json={"include_diary": False, "include_picturebooks": True},
        )
        assert book_only.status_code == 200

        both = alice.post(
            "/api/export/day/2026-08-08/pdf",
            json={"include_diary": True, "include_picturebooks": True},
        )
        assert both.status_code == 200
        assert 'filename="zhiji-2026-08-08.pdf"' in both.headers["content-disposition"]


def test_day_pdf_empty_selection_rejected(film_app):
    app, db_path = film_app
    with two_clients(app, db_path) as ((alice, alice_id), _):
        _seed_day(db_path, alice_id)
        response = alice.post(
            "/api/export/day/2026-08-08/pdf",
            json={"include_diary": False, "include_picturebooks": False},
        )
        assert response.status_code == 422


def test_day_pdf_no_body_keeps_legacy_flow(film_app):
    app, db_path = film_app
    with two_clients(app, db_path) as ((alice, alice_id), _):
        _seed_day(db_path, alice_id)
        legacy = alice.post("/api/export/day/2026-08-08/pdf")
        assert legacy.status_code == 200


def test_day_pdf_invalid_date_rejected(film_app):
    app, _ = film_app
    with two_clients(app) as ((alice, _), _2):
        assert alice.post("/api/export/day/not-a-date/pdf").status_code == 400
        assert alice.get("/api/export/day/2026-13-99/availability").status_code == 400


def test_time_story_pdf_only_completed_owned(film_app):
    app, db_path = film_app
    with two_clients(app, db_path) as ((alice, alice_id), (bob, bob_id)):
        seed_completed_work_book(
            db_path, alice_id, 101, 201, kind="time_story", title="长线",
            start="2026-08-01", end="2026-08-05",
        )
        seed_completed_work_book(db_path, alice_id, 102, 202, title="当日")

        exported = alice.post("/api/export/time-story/101/pdf")
        assert exported.status_code == 200
        assert 'filename="zhiji-time-story-101.pdf"' in (
            exported.headers["content-disposition"]
        )

        # 非 time_story 作品不导出。
        assert alice.post("/api/export/time-story/102/pdf").status_code == 404
        # 越权不导出。
        assert bob.post("/api/export/time-story/101/pdf").status_code == 404
        # 不存在。
        assert alice.post("/api/export/time-story/999/pdf").status_code == 404
