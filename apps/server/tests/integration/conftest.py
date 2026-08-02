"""Integration-test fixtures backed by a real PostgreSQL instance.

Each test runs against a throwaway, per-process ``agentcore_it_<pid>`` schema that
is created and dropped per test, so integration tests never touch dev data, stay
isolated from one another, and — crucially — don't collide when several pytest
processes (parallel agents / pytest-xdist workers) hit the same server at once.
Using a dedicated *schema* (not a separate database) means no CREATEDB privilege
is required — the app role already owns its database.

Tests auto-skip when no PostgreSQL is reachable, keeping unit-only runs green.
The target server comes from ``TEST_DATABASE_URL`` (falls back to the app's
``DATABASE_URL``).
"""

import os
from collections.abc import AsyncIterator, Callable, Iterator
from contextlib import asynccontextmanager

import httpx
import pytest
import pytest_asyncio
from httpx import ASGITransport
from sqlalchemy import text
from sqlalchemy.exc import InterfaceError, OperationalError
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

import agentcore.db.models  # noqa: F401  (register models on Base.metadata)
from agentcore.api.dependencies import get_db
from agentcore.config import settings
from agentcore.db.base import Base
from agentcore.db.base import engine as app_engine
from agentcore.db.base import telemetry_engine as app_telemetry_engine
from agentcore.db.repositories import (
    AdminMfaRepository,
    CredentialsRepository,
    UserRepository,
)
from agentcore.db.repositories.chat import OFFICIAL_CHAT_ID, OFFICIAL_CHAT_TITLE
from agentcore.main import app
from agentcore.security import hash_password
from agentcore.security.keys import KeyEncryptor

_TEST_MFA_SECRET = "JBSWY3DPEHPK3PXP"
_MASTER_KEY = "ab" * 32
TEST_PASSWORD = "password123"


async def register_and_login(
    client: httpx.AsyncClient,
    username: str,
    *,
    platform: str = "desktop",
    password: str = TEST_PASSWORD,
) -> str:
    """Register a product user and complete cookie login (product sessions have no MFA).

    Returns the signed-in user's id from ``LoginResponse.user``.
    """
    r = await client.post(
        "/v1/auth/register",
        json={"username": username, "password": password},
    )
    assert r.status_code == 201, r.text
    r = await client.post(
        "/v1/auth/login",
        json={"username": username, "password": password},
        headers={"X-Client-Platform": platform},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert not body.get("mfa_required"), body
    user = body.get("user")
    assert user is not None, body
    return user["id"]


async def login_admin(client: httpx.AsyncClient, username: str, password: str) -> None:
    """Complete admin login (password + TOTP) on the admin client platform."""
    import pyotp

    r = await client.post(
        "/v1/auth/login",
        json={"username": username, "password": password},
        headers={"X-Client-Platform": "admin"},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    if body.get("mfa_required"):
        code = pyotp.TOTP(_TEST_MFA_SECRET).now()
        r = await client.post(
            "/v1/auth/login/mfa",
            json={"pending_token": body["pending_token"], "code": code},
        )
        assert r.status_code == 200, r.text


@pytest.fixture(autouse=True)
def _test_encryption_key(monkeypatch) -> Iterator[None]:
    """BYOK + admin MFA tests need a configured master key."""
    monkeypatch.setattr(settings, "encryption_key", _MASTER_KEY)
    yield


# Cookie-session integration tests predate CSRF; keep them green unless marked @pytest.mark.csrf.
@pytest.fixture(autouse=True)
def _disable_csrf_unless_marked(monkeypatch, request):
    if request.node.get_closest_marker("csrf") or "test_csrf" in request.module.__name__:
        return
    monkeypatch.setattr(settings, "csrf_enabled", False)


# Per-process schema so concurrent test runs never DROP/CREATE the *same* schema
# out from under each other. A shared name lets a second pytest process (parallel
# agent / pytest-xdist worker) wipe the first run's rows mid-test ("用户名或密码错误")
# or race its CREATE ("schema already exists"). PID is unique per live process and
# distinguishes xdist workers (each a separate process); the per-test
# DROP-before-CREATE below still self-heals a same-PID orphan from a crashed run.
_TEST_SCHEMA = f"agentcore_it_{os.getpid()}"


def _test_db_url() -> str:
    return os.environ.get("TEST_DATABASE_URL") or settings.database_url


@pytest_asyncio.fixture
async def session_factory() -> AsyncIterator[async_sessionmaker]:
    # search_path = our schema only (plus implicit pg_catalog): keeps create_all
    # from seeing dev tables in `public` and skipping table creation.
    engine = create_async_engine(
        _test_db_url(),
        connect_args={"server_settings": {"search_path": _TEST_SCHEMA}},
        poolclass=NullPool,
    )
    try:
        async with engine.begin() as conn:
            await conn.execute(text(f"DROP SCHEMA IF EXISTS {_TEST_SCHEMA} CASCADE"))
            await conn.execute(text(f"CREATE SCHEMA {_TEST_SCHEMA}"))
            await conn.run_sync(Base.metadata.create_all)
            # Mirror the official-chat migration seed (create_all does not run
            # alembic data inserts). Required so notice publish → IM works.
            await conn.execute(
                text(
                    """
                    INSERT INTO chats (id, type, title, auto_join, created_at, updated_at)
                    VALUES (CAST(:id AS uuid), 'official', :title, true, now(), now())
                    ON CONFLICT (id) DO NOTHING
                    """
                ),
                {"id": OFFICIAL_CHAT_ID, "title": OFFICIAL_CHAT_TITLE},
            )
    except (OperationalError, InterfaceError, OSError) as exc:
        await engine.dispose()
        pytest.skip(f"PostgreSQL not available for integration tests: {exc}")

    factory = async_sessionmaker(engine, expire_on_commit=False)

    async def _override_get_db() -> AsyncIterator:
        async with factory() as session:
            yield session

    app.dependency_overrides[get_db] = _override_get_db
    try:
        yield factory
    finally:
        app.dependency_overrides.pop(get_db, None)
        async with engine.begin() as conn:
            await conn.execute(text(f"DROP SCHEMA IF EXISTS {_TEST_SCHEMA} CASCADE"))
        await engine.dispose()


@pytest_asyncio.fixture
async def client(session_factory) -> AsyncIterator[httpx.AsyncClient]:
    transport = ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


@pytest.fixture
def new_client(session_factory) -> Callable:
    """Factory for additional clients with independent cookie jars (e.g. IDOR tests)."""

    @asynccontextmanager
    async def _make() -> AsyncIterator[httpx.AsyncClient]:
        transport = ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
            yield c

    return _make


@pytest_asyncio.fixture(autouse=True)
async def _dispose_app_engine_pool() -> AsyncIterator[None]:
    """Drain the process-global engine's pool after each test.

    ``database_ready()`` (readiness probe + admin 系统/概览 panels) pings the global
    ``engine`` directly, *not* the per-test ``get_db`` override. With function-scoped
    event loops a pooled connection binds to the first test's loop, so the next test
    that probes hits a connection on a closed loop ("Event loop is closed"). Disposing
    here — inside each test's own loop — guarantees the next probe opens fresh.
    """
    yield
    await app_engine.dispose()
    await app_telemetry_engine.dispose()


@pytest.fixture(autouse=True)
def _disable_rate_limit() -> Iterator[None]:
    """Rate-limit state is process-global; disable it so per-IP counters don't
    accumulate across the many auth POSTs the suite makes (429 is covered by the
    dedicated unit tests in test_rate_limit.py)."""
    original = settings.rate_limit_enabled
    settings.rate_limit_enabled = False
    yield
    settings.rate_limit_enabled = original


@pytest.fixture(autouse=True)
def _open_registration(monkeypatch) -> None:
    """Almost every integration test seeds throwaway users via ``register_and_login``;
    pin registration open so a local ``.env`` (``REGISTRATION_OPEN=false`` — a legitimate
    prod/local config) can't 403 them during setup. Tests that specifically exercise
    closed registration re-patch it to False in-body, which overrides this (same
    function-scoped monkeypatch, applied after fixture setup)."""
    monkeypatch.setattr(settings, "registration_open", True)


@pytest.fixture(autouse=True)
def _pin_billing_mode_byok(monkeypatch) -> None:
    """Pin billing_mode=byok so a local ``.env`` with ``BILLING_MODE=platform``
    cannot open the platform catalog for keyless-BYOK tests that expect 402."""
    monkeypatch.setattr(settings, "billing_mode", "byok")


@pytest_asyncio.fixture
async def make_admin(session_factory) -> Callable:
    """Return an async helper that seeds an admin user (with credentials)."""

    async def _make(username: str = "admin", password: str = "adminpass123") -> tuple[str, str]:
        enc = KeyEncryptor(_MASTER_KEY)
        async with session_factory() as session:
            user = await UserRepository(session).create(
                username=username, display_name=username, role="admin"
            )
            await CredentialsRepository(session).create(
                user_id=user.user_id, password_hash=hash_password(password)
            )
            await AdminMfaRepository(session).upsert_pending(
                user_id=user.user_id,
                totp_secret_enc=enc.encrypt(_TEST_MFA_SECRET.encode()),
            )
            await AdminMfaRepository(session).enable(
                user.user_id,
                recovery_codes_hash=[],
            )
        return username, password

    return _make
