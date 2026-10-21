from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from pathlib import Path

import anyio
import httpx
from typing_extensions import override

from agent.app_runtime import AppSettings, RuntimeFactories
from agent.contracts import ContractModel
from agent.essay_fake import essay_response
from agent.essay_llm import GenerationResult, ModelRole, Output, OutputRecovery, Stage
from agent.fake_llm import FakeLLM
from server import create_app


@asynccontextmanager
async def client_for(
    path: Path, factories: RuntimeFactories | None = None
) -> AsyncGenerator[httpx.AsyncClient]:
    app = create_app(AppSettings(backend="fake", db_path=path, mcp_enabled=False), factories)
    async with (
        app.router.lifespan_context(app),
        httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://test",
            headers={"Content-Type": "application/json"},
        ) as client,
    ):
        yield client


class ControlledLLM(FakeLLM):
    def __init__(self, role: ModelRole) -> None:
        super().__init__(role, essay_response)
        self.calls: list[Stage] = []
        self.closed: bool = False
        self.entered: anyio.Event = anyio.Event()
        self.release: anyio.Event = anyio.Event()
        self.slow: bool = False

    @override
    async def generate(
        self,
        stage: Stage,
        payload: ContractModel,
        output_model: type[Output],
        *,
        recover: OutputRecovery | None = None,
    ) -> GenerationResult[Output]:
        self.calls.append(stage)
        self.entered.set()
        if self.slow:
            await self.release.wait()
        return await super().generate(stage, payload, output_model, recover=recover)

    @override
    async def aclose(self) -> None:
        self.closed = True


class Providers:
    def __init__(self) -> None:
        self.fast: ControlledLLM = ControlledLLM("fast")
        self.quality: ControlledLLM = ControlledLLM("quality")
        self.fast_builds: int = 0
        self.quality_builds: int = 0

    def build_fast(self, settings: AppSettings) -> ControlledLLM:
        del settings
        self.fast_builds += 1
        return self.fast

    def build_quality(self, settings: AppSettings) -> ControlledLLM:
        del settings
        self.quality_builds += 1
        return self.quality

    def factories(self) -> RuntimeFactories:
        return RuntimeFactories(fast=self.build_fast, quality=self.build_quality)
