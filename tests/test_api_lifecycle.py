from dataclasses import replace
from pathlib import Path

import anyio
import httpx
import pytest
from fastapi import FastAPI
from typing_extensions import override

from agent.api_models import ChatResponse, HealthResponse
from agent.app_runtime import ApplicationRuntime, AppSettings
from agent.contracts import EssayRequest
from agent.essay_llm import EssayLLM
from agent.mcp_client import MCPClient
from agent.session_store import SqliteSessionStore
from server import create_app
from tests.api_support import Providers

pytestmark = pytest.mark.anyio


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


class OwnedMCP(MCPClient):
    def __init__(self) -> None:
        super().__init__({})
        self.started_by: int | None = None
        self.stopped_by: int | None = None

    @override
    async def start(self) -> None:
        self.started_by = anyio.get_current_task().id
        await super().start()

    @override
    async def stop(self) -> None:
        self.stopped_by = anyio.get_current_task().id
        await super().stop()


async def test_singleton_lifespan_and_same_task_mcp_cleanup(tmp_path: Path) -> None:
    providers = Providers()
    mcp = OwnedMCP()
    settings = AppSettings(backend="fake", db_path=tmp_path / "life.db")
    app = create_app(settings, replace(providers.factories(), mcp=lambda: mcp))
    async with (
        app.router.lifespan_context(app),
        httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client,
    ):
        first = HealthResponse.model_validate_json((await client.get("/health")).text)
        for _ in range(2):
            response = await client.post("/chat", json={})
            assert response.status_code == 200
            assert ChatResponse.model_validate_json(response.text).result.body
        second = HealthResponse.model_validate_json((await client.get("/health")).text)
        assert first.instance_id == second.instance_id
        assert first.creation_count == second.creation_count == 1
        assert providers.fast_builds == providers.quality_builds == 1
    assert providers.fast.closed
    assert providers.quality.closed
    assert mcp.started_by == mcp.stopped_by
    assert mcp.sessions == {}


async def test_mcp_start_failure_still_drafts(tmp_path: Path) -> None:
    providers = Providers()
    app = create_app(
        AppSettings(backend="fake", db_path=tmp_path / "mcp.db"),
        replace(providers.factories(), mcp=lambda: MCPClient({"missing": tmp_path / "missing.py"})),
    )
    async with (
        app.router.lifespan_context(app),
        httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client,
    ):
        health = HealthResponse.model_validate_json((await client.get("/health")).text)
        assert health.mcp_status == "unavailable"
        response = await client.post("/chat", json={"company_name": "테스트 회사"})
        assert response.status_code == 200
        assert ChatResponse.model_validate_json(response.text).result.body


class ClosedStore(SqliteSessionStore):
    def __init__(self, path: Path) -> None:
        super().__init__(path)
        self.closed: bool = False

    @override
    def close(self) -> None:
        super().close()
        self.closed = True


def failed_quality(settings: AppSettings) -> EssayLLM:
    del settings
    code = "injected_configuration_failure"
    raise ValueError(code)


async def test_partial_startup_closes_constructed_resources(tmp_path: Path) -> None:
    providers = Providers()
    store = ClosedStore(tmp_path / "partial.db")

    def existing_store(path: Path) -> SqliteSessionStore:
        assert path == tmp_path / "partial.db"
        return store

    factories = replace(providers.factories(), quality=failed_quality, store=existing_store)
    app = create_app(
        AppSettings(backend="fake", db_path=tmp_path / "partial.db", mcp_enabled=False), factories
    )
    with pytest.raises(ValueError, match="injected_configuration_failure"):
        async with app.router.lifespan_context(app):
            pytest.fail("startup should reject failed provider construction")
    assert providers.fast.closed
    assert store.closed


async def test_shutdown_cancels_worker_and_records_interrupted(tmp_path: Path) -> None:
    providers = Providers()
    providers.fast.slow = True
    path = tmp_path / "shutdown.db"
    runtime = ApplicationRuntime(
        AppSettings(backend="fake", db_path=path, mcp_enabled=False), providers.factories()
    )
    request = EssayRequest()
    async with runtime.lifespan(FastAPI()):
        handle = await runtime.require_service().submit(request)
        await providers.fast.entered.wait()
    assert handle.terminal is not None
    assert handle.terminal.event == "RunError"
    assert providers.fast.closed
    store = SqliteSessionStore(path)
    try:
        record = store.get(request.request_id)
        assert record is not None
        assert record.status == "interrupted"
    finally:
        store.close()
