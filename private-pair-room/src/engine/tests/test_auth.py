import hashlib
import importlib
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient


COOKIE_NAME = "zhiji_session"
FRONTEND_ORIGIN = "http://localhost:5173"
FOREIGN_ORIGIN = "https://attacker.example"
PASSWORD = "correct horse battery"


@pytest.fixture
def auth_app(tmp_path, monkeypatch):
    db_path = tmp_path / "auth.sqlite3"
    monkeypatch.setenv("ZHIJI_DB_PATH", str(db_path))
    monkeypatch.setenv("ZHIJI_UPLOAD_DIR", str(tmp_path / "uploads"))
    monkeypatch.setenv(
        "FRONTEND_ORIGINS",
        f" {FRONTEND_ORIGIN},https://frontend.example ",
    )
    monkeypatch.setenv("SESSION_COOKIE_SECURE", "false")
    monkeypatch.setenv("SESSION_TTL_SECONDS", "3600")

    import config
    import database
    import main

    importlib.reload(config)
    importlib.reload(database)
    main = importlib.reload(main)
    return main.app, db_path


@contextmanager
def client_for(app):
    with TestClient(app, base_url="http://testserver") as client:
        yield client


def register(client, username="Nart", nickname="纳特", password=PASSWORD, **kwargs):
    return client.post(
        "/api/auth/register",
        json={"username": username, "password": password, "nickname": nickname},
        **kwargs,
    )


def token_hash(raw_token):
    return hashlib.sha256(raw_token.encode("utf-8")).hexdigest()


def fetch_one(db_path, sql, params=()):
    with sqlite3.connect(db_path) as db:
        db.row_factory = sqlite3.Row
        return db.execute(sql, params).fetchone()


def execute(db_path, sql, params=()):
    with sqlite3.connect(db_path) as db:
        db.execute(sql, params)
        db.commit()


def test_register_creates_profile_account_session_cookie_and_me(auth_app):
    app, db_path = auth_app
    with client_for(app) as client:
        response = register(client)

        assert response.status_code == 201
        set_cookie = response.headers["set-cookie"]
        assert set_cookie.startswith(f"{COOKIE_NAME}=")
        assert "HttpOnly" in set_cookie
        assert "SameSite=lax" in set_cookie
        assert "Path=/" in set_cookie
        assert "Secure" not in set_cookie

        me = client.get("/api/me")
        assert me.status_code == 200
        assert set(me.json()) == {
            "id",
            "nickname",
            "avatar_url",
            "signature",
            "created_at",
        }
        assert me.json()["nickname"] == "纳特"

        account = fetch_one(
            db_path,
            "SELECT a.user_id, a.username_norm, a.password_hash, p.nickname "
            "FROM accounts a JOIN profile p ON p.id = a.user_id",
        )
        assert dict(account) | {} == {
            "user_id": me.json()["id"],
            "username_norm": "nart",
            "password_hash": account["password_hash"],
            "nickname": "纳特",
        }
        assert account["password_hash"].startswith("$argon2id$")
        from auth.security import password_needs_rehash, verify_password

        assert verify_password(PASSWORD, account["password_hash"]) is True
        assert verify_password("not the password", account["password_hash"]) is False
        assert verify_password(PASSWORD, "not-a-phc-hash") is False
        assert password_needs_rehash("not-a-phc-hash") is True

        raw_token = client.cookies[COOKIE_NAME]
        session = fetch_one(
            db_path,
            "SELECT user_id, token_hash, expires_at, revoked_at FROM auth_sessions",
        )
        assert session["user_id"] == me.json()["id"]
        assert session["token_hash"] == token_hash(raw_token)
        assert raw_token != session["token_hash"]
        assert session["expires_at"]
        assert session["revoked_at"] is None


def test_database_never_contains_plaintext_password_or_raw_session_token(auth_app):
    app, db_path = auth_app
    unique_password = "river otter battery 764921"
    with client_for(app) as client:
        response = register(client, password=unique_password)
        assert response.status_code == 201
        raw_token = client.cookies[COOKIE_NAME]

    database_bytes = db_path.read_bytes()
    assert unique_password.encode() not in database_bytes
    assert raw_token.encode() not in database_bytes


def test_register_rejects_password_shorter_than_eight_characters(auth_app):
    app, db_path = auth_app
    with client_for(app) as client:
        response = register(client, password="1234567")

    assert response.status_code == 422
    counts = fetch_one(
        db_path,
        "SELECT (SELECT COUNT(*) FROM profile) AS profiles, "
        "(SELECT COUNT(*) FROM accounts) AS accounts, "
        "(SELECT COUNT(*) FROM auth_sessions) AS sessions",
    )
    assert dict(counts) == {"profiles": 0, "accounts": 0, "sessions": 0}


def test_login_remains_compatible_with_a_legacy_short_password(auth_app):
    app, db_path = auth_app
    from auth.security import hash_password

    with client_for(app) as client:
        with sqlite3.connect(db_path) as db:
            cursor = db.execute("INSERT INTO profile (nickname) VALUES ('旧账号')")
            db.execute(
                "INSERT INTO accounts (user_id, username_norm, password_hash) "
                "VALUES (?, 'legacy', ?)",
                (cursor.lastrowid, hash_password("short")),
            )
            db.commit()

        response = client.post(
            "/api/auth/login",
            json={"username": "legacy", "password": "short"},
        )

    assert response.status_code == 200
    assert response.json()["nickname"] == "旧账号"


def test_username_normalization_rejects_nfkc_trimmed_casefold_duplicate(auth_app):
    app, db_path = auth_app
    with client_for(app) as first, client_for(app) as second:
        assert register(first, username="  ＮａＲｔ  ").status_code == 201
        duplicate = register(second, username="nart", nickname="另一人")

    assert duplicate.status_code == 409
    assert duplicate.json() == {"detail": "username unavailable"}
    counts = fetch_one(
        db_path,
        "SELECT (SELECT COUNT(*) FROM profile) AS profiles, "
        "(SELECT COUNT(*) FROM accounts) AS accounts, "
        "(SELECT COUNT(*) FROM auth_sessions) AS sessions",
    )
    assert dict(counts) == {"profiles": 1, "accounts": 1, "sessions": 1}


def test_invalid_credentials_do_not_reveal_username_existence(auth_app):
    app, _ = auth_app
    with client_for(app) as client:
        assert register(client).status_code == 201
        client.cookies.clear()

        wrong_password = client.post(
            "/api/auth/login",
            json={"username": "NART", "password": "definitely wrong"},
        )
        missing_username = client.post(
            "/api/auth/login",
            json={"username": "missing", "password": "definitely wrong"},
        )

    assert wrong_password.status_code == 401
    assert missing_username.status_code == 401
    assert wrong_password.json() == missing_username.json() == {
        "detail": "invalid credentials"
    }


def test_login_accepts_normalized_username_and_creates_session(auth_app):
    app, db_path = auth_app
    with client_for(app) as client:
        assert register(client, username="Ｎａｒｔ").status_code == 201
        first_token = client.cookies[COOKIE_NAME]
        client.cookies.clear()

        login = client.post(
            "/api/auth/login",
            json={"username": "  NART ", "password": PASSWORD},
        )

        assert login.status_code == 200
        second_token = client.cookies[COOKIE_NAME]
        assert second_token != first_token
        assert client.get("/api/me").json()["nickname"] == "纳特"

    session_count = fetch_one(
        db_path, "SELECT COUNT(*) AS count FROM auth_sessions"
    )["count"]
    assert session_count == 2


def test_absent_expired_and_revoked_sessions_return_401(auth_app):
    app, db_path = auth_app
    with client_for(app) as client:
        assert client.get("/api/me").status_code == 401

        assert register(client).status_code == 201
        expired_hash = token_hash(client.cookies[COOKIE_NAME])
        execute(
            db_path,
            "UPDATE auth_sessions SET expires_at = ? WHERE token_hash = ?",
            ("2000-01-01T00:00:00+00:00", expired_hash),
        )
        assert client.get("/api/me").status_code == 401

        login = client.post(
            "/api/auth/login",
            json={"username": "nart", "password": PASSWORD},
        )
        assert login.status_code == 200
        revoked_hash = token_hash(client.cookies[COOKIE_NAME])
        execute(
            db_path,
            "UPDATE auth_sessions SET revoked_at = ? WHERE token_hash = ?",
            (datetime.now(timezone.utc).isoformat(), revoked_hash),
        )
        assert client.get("/api/me").status_code == 401


def test_logout_revokes_current_session_and_clears_cookie(auth_app):
    app, db_path = auth_app
    with client_for(app) as client:
        assert register(client).status_code == 201
        current_hash = token_hash(client.cookies[COOKIE_NAME])

        logout = client.delete("/api/auth/session")

        assert logout.status_code == 204
        assert COOKIE_NAME not in client.cookies
        clear_cookie = logout.headers["set-cookie"]
        assert clear_cookie.startswith(f'{COOKIE_NAME}=""')
        assert "Max-Age=0" in clear_cookie
        assert "HttpOnly" in clear_cookie
        assert "SameSite=lax" in clear_cookie
        assert "Path=/" in clear_cookie
        assert client.get("/api/me").status_code == 401

    session = fetch_one(
        db_path,
        "SELECT revoked_at FROM auth_sessions WHERE token_hash = ?",
        (current_hash,),
    )
    assert session["revoked_at"] is not None


@pytest.mark.parametrize(
    ("method", "path", "payload"),
    [
        (
            "post",
            "/api/auth/register",
            {"username": "other", "password": PASSWORD, "nickname": "其他"},
        ),
        (
            "post",
            "/api/auth/login",
            {"username": "nart", "password": PASSWORD},
        ),
        ("delete", "/api/auth/session", None),
    ],
)
def test_mutating_auth_requests_reject_foreign_origin(
    auth_app, method, path, payload
):
    app, _ = auth_app
    with client_for(app) as client:
        if path != "/api/auth/register":
            assert register(client).status_code == 201

        response = client.request(
            method,
            path,
            json=payload,
            headers={"Origin": FOREIGN_ORIGIN},
        )

    assert response.status_code == 403
    assert response.json() == {"detail": "origin not allowed"}


def test_configured_origin_is_allowed_for_auth_mutation(auth_app):
    app, _ = auth_app
    with client_for(app) as client:
        response = register(client, headers={"Origin": FRONTEND_ORIGIN})

    assert response.status_code == 201
    assert response.headers["access-control-allow-origin"] == FRONTEND_ORIGIN
    assert response.headers["access-control-allow-credentials"] == "true"


def test_cors_preflight_allows_only_exact_configured_origins(auth_app):
    app, _ = auth_app
    preflight_headers = {
        "Access-Control-Request-Method": "POST",
        "Access-Control-Request-Headers": "content-type",
    }
    with client_for(app) as client:
        configured = client.options(
            "/api/auth/login",
            headers={"Origin": FRONTEND_ORIGIN, **preflight_headers},
        )
        unconfigured = client.options(
            "/api/auth/login",
            headers={"Origin": FOREIGN_ORIGIN, **preflight_headers},
        )

    assert configured.status_code == 200
    assert configured.headers["access-control-allow-origin"] == FRONTEND_ORIGIN
    assert configured.headers["access-control-allow-credentials"] == "true"
    assert unconfigured.status_code == 400
    assert "access-control-allow-origin" not in unconfigured.headers
    assert configured.headers["access-control-allow-origin"] != "*"

    cors_options = next(
        middleware.kwargs
        for middleware in app.user_middleware
        if middleware.cls.__name__ == "CORSMiddleware"
    )
    assert cors_options["allow_credentials"] is True
    assert "*" not in cors_options["allow_origins"]


def test_independent_cookie_jars_resolve_different_current_users(auth_app):
    app, db_path = auth_app
    with client_for(app) as first, client_for(app) as second:
        assert register(first, username="first", nickname="甲").status_code == 201
        assert register(second, username="second", nickname="乙").status_code == 201

        first_me = first.get("/api/me")
        second_me = second.get("/api/me")
        assert first.cookies[COOKIE_NAME] != second.cookies[COOKIE_NAME]

    assert first_me.status_code == second_me.status_code == 200
    assert first_me.json()["nickname"] == "甲"
    assert second_me.json()["nickname"] == "乙"
    assert first_me.json()["id"] != second_me.json()["id"]
    distinct_hashes = fetch_one(
        db_path,
        "SELECT COUNT(DISTINCT password_hash) AS count FROM accounts",
    )["count"]
    assert distinct_hashes == 2


def test_default_frontend_origins_match_vite_dev_server(monkeypatch):
    import config

    monkeypatch.delenv("FRONTEND_ORIGINS", raising=False)

    assert config.get_frontend_origins() == [
        "http://localhost:3000",
        "http://127.0.0.1:3000",
    ]
