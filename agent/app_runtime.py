"""Lifespan-owned configuration and injectable factories without import-time secrets."""

import logging
import os
from collections.abc import AsyncGenerator, Callable
from contextlib import AsyncExitStack, asynccontextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Literal
from uuid import UUID, uuid4

import anyio
from dotenv import load_dotenv
from fastapi import FastAPI

from .api_models import HealthResponse, ServiceError, run_error
from .deps import SupervisorDeps
from .essay_fake import essay_response
from .essay_llm import EssayLLM, parse_backend
from .fake_llm import FastLLM, QualityLLM
from .graph import build_graph
from .graph_state import EssayState, EssayUpdate
from .langgraph_boundary import CompiledGraph
from .mcp_client import MCPClient
from .openai_llm import OpenAIFastLLM, OpenAIQualityLLM
from .run_service import RunService
from .run_worker import RunExecutor
from .session_store import DB_PATH, SqliteSessionStore

LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class AppSettings:
    """Public runtime choices; credentials stay inside provider construction."""

    backend: Literal["openai", "fake"] = "openai"
    fast_model: str = "gpt-4o-mini"
    quality_model: str = "gpt-4o"
    db_path: Path = DB_PATH
    mcp_enabled: bool = True


def load_settings() -> AppSettings:
    """Read runtime configuration only at startup; tests inject explicit settings."""
    if os.getenv("ESSAY_LOAD_DOTENV", "1") == "1":
        _ = load_dotenv(Path(__file__).resolve().parent.parent / ".env", override=False)
    return AppSettings(
        backend=parse_backend(os.getenv("LLM_BACKEND", "openai")),
        fast_model=os.getenv("OPENAI_FAST_MODEL", "gpt-4o-mini"),
        quality_model=os.getenv("OPENAI_QUALITY_MODEL", "gpt-4o"),
        db_path=Path(os.getenv("ESSAY_DB_PATH", str(DB_PATH))),
        mcp_enabled=os.getenv("ESSAY_MCP_ENABLED", "1") == "1",
    )


def _fast(settings: AppSettings) -> EssayLLM:
    return (
        FastLLM(essay_response)
        if settings.backend == "fake"
        else OpenAIFastLLM(settings.fast_model)
    )


def _quality(settings: AppSettings) -> EssayLLM:
    return (
        QualityLLM(essay_response)
        if settings.backend == "fake"
        else OpenAIQualityLLM(settings.quality_model)
    )


@dataclass(frozen=True, slots=True)
class RuntimeFactories:
    """Tests replace resource factories without changing product backend behavior."""

    fast: Callable[[AppSettings], EssayLLM] = _fast
    quality: Callable[[AppSettings], EssayLLM] = _quality
    mcp: Callable[[], MCPClient] = MCPClient
    store: Callable[[Path], SqliteSessionStore] = SqliteSessionStore
    graph: Callable[[SupervisorDeps], CompiledGraph[EssayState, EssayUpdate]] = build_graph


class ApplicationRuntime:
    """Hold lifecycle identity, not per-request generated content."""

    def __init__(self, settings: AppSettings | None, factories: RuntimeFactories) -> None:
        """Defer resource creation until FastAPI enters its lifespan."""
        self.settings: AppSettings | None = settings
        self.factories: RuntimeFactories = factories
        self.service: RunService | None = None
        self.creation_count: int = 0
        self.instance_id: UUID = uuid4()
        self.mcp_status: Literal["ready", "unavailable", "disabled"] = "disabled"

    def require_service(self) -> RunService:
        """Reject requests outside the initialized lifespan with a safe envelope."""
        if self.service is None:
            raise ServiceError(503, run_error(None, "not_ready", "서버가 준비 중입니다."))
        return self.service

    def health(self) -> HealthResponse:
        """Expose only nonsecret configuration and singleton initialization counts."""
        service = self.require_service()
        settings = self.settings
        if settings is None:
            code = "settings_missing"
            raise RuntimeError(code)
        return HealthResponse(
            instance_id=self.instance_id,
            creation_count=self.creation_count,
            llm_backend=settings.backend,
            fast_model="fake:fast" if settings.backend == "fake" else settings.fast_model,
            quality_model="fake:quality" if settings.backend == "fake" else settings.quality_model,
            mcp_status=self.mcp_status,
            active_runs=len(service.active),
        )

    @asynccontextmanager
    async def lifespan(self, app: FastAPI) -> AsyncGenerator[None]:
        """Close joined workers before MCP, provider clients and SQLite, on their owner task."""
        del app
        settings = self.settings or load_settings()
        self.settings = settings
        async with AsyncExitStack() as resources:
            store = await anyio.to_thread.run_sync(self.factories.store, settings.db_path)
            _ = resources.push_async_callback(anyio.to_thread.run_sync, store.close)
            _ = await anyio.to_thread.run_sync(store.interrupt_orphans, frozenset[UUID]())
            fast, quality = await self._build_llms(settings, resources)
            mcp = await self._start_mcp(settings, resources)
            graph = self.factories.graph(SupervisorDeps(fast, quality, mcp, store))
            async with anyio.create_task_group() as group:
                service = RunService(RunExecutor(store, graph), group)
                self.service = service
                self.creation_count += 1
                try:
                    yield
                finally:
                    await service.shutdown()
            self.service = None

    async def _build_llms(
        self, settings: AppSettings, resources: AsyncExitStack
    ) -> tuple[EssayLLM, EssayLLM]:
        fast = self.factories.fast(settings)
        _ = resources.push_async_callback(fast.aclose)
        quality = self.factories.quality(settings)
        _ = resources.push_async_callback(quality.aclose)
        return fast, quality

    async def _start_mcp(
        self, settings: AppSettings, resources: AsyncExitStack
    ) -> MCPClient | None:
        if not settings.mcp_enabled:
            return None
        mcp = self.factories.mcp()
        _ = resources.push_async_callback(mcp.stop)
        try:
            await mcp.start()
        except (OSError, RuntimeError, TimeoutError):
            LOGGER.warning("Essay MCP startup unavailable; local guides remain available")
        self.mcp_status = "ready" if mcp.sessions else "unavailable"
        return mcp
