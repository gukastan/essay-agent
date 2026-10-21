import socket
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from pathlib import Path

import anyio
import httpx
import pytest
import uvicorn
from pydantic import TypeAdapter
from typing_extensions import override

from agent.api_models import ChatResponse, HealthResponse, RunLookup
from agent.app_runtime import AppSettings
from agent.contracts import EssayRequest, FinalResult
from server import create_app
from tests.api_support import Providers
from tests.test_api_http import parse_events

pytestmark = pytest.mark.anyio


class ReadyServer(uvicorn.Server):
    def __init__(self, config: uvicorn.Config) -> None:
        super().__init__(config)
        self.ready: anyio.Event = anyio.Event()

    @override
    async def startup(self, sockets: list[socket.socket] | None = None) -> None:
        await super().startup(sockets)
        self.ready.set()


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@asynccontextmanager
async def live_client(path: Path, providers: Providers) -> AsyncGenerator[httpx.AsyncClient]:
    app = create_app(
        AppSettings(backend="fake", db_path=path, mcp_enabled=False), providers.factories()
    )
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        port = TypeAdapter(tuple[str, int]).validate_python(listener.getsockname())[1]
        server = ReadyServer(uvicorn.Config(app, log_level="critical", lifespan="on", ws="none"))
        async with anyio.create_task_group() as group:

            async def serve() -> None:
                await server.serve(sockets=[listener])

            _ = group.start_soon(serve)
            with anyio.fail_after(5):
                await server.ready.wait()
            try:
                async with httpx.AsyncClient(
                    base_url=f"http://127.0.0.1:{port}",
                    headers={"Content-Type": "application/json"},
                ) as client:
                    yield client
            finally:
                providers.fast.release.set()
                providers.quality.release.set()
                server.should_exit = True


async def test_real_disconnect_completes_and_can_be_queried(tmp_path: Path) -> None:
    providers = Providers()
    providers.fast.slow = True
    request = EssayRequest()
    async with live_client(tmp_path / "network.db", providers) as client:
        async with client.stream(
            "POST", "/chat/stream", content=request.model_dump_json()
        ) as response:
            assert response.status_code == 200
            async for line in response.aiter_lines():
                if line.startswith("data: "):
                    assert '"StageStarted"' in line
                    break
        await providers.fast.entered.wait()
        providers.fast.release.set()
        with anyio.fail_after(5):
            while True:
                lookup = RunLookup.model_validate_json(
                    (await client.get(f"/runs/{request.request_id}")).text
                )
                if lookup.status == "completed":
                    break
                await anyio.sleep(0.01)
        assert lookup.result is not None
        replay = ChatResponse.model_validate_json(
            (await client.post("/chat", content=request.model_dump_json())).text
        )
        assert replay.result == lookup.result
        assert len(providers.fast.calls) == 2
        assert len(providers.quality.calls) == 3
        health = HealthResponse.model_validate_json((await client.get("/health")).text)
        assert health.active_runs == 0


async def test_real_sse_transcript_matches_persisted_terminal(tmp_path: Path) -> None:
    providers = Providers()
    request = EssayRequest(question="경험이 부족해도 작성해 주세요.")
    async with live_client(tmp_path / "transcript.db", providers) as client:
        response = await client.post("/chat/stream", content=request.model_dump_json())
        assert response.status_code == 200
        events = parse_events(response.text)
        terminals = [event for event in events if event.event in ("FinalResult", "RunError")]
        assert len(terminals) == 1
        terminal = terminals[0]
        assert isinstance(terminal, FinalResult)
        assert terminal.persistence_status == "stored"
        assert response.text.endswith("data: [DONE]\n\n")
        lookup = RunLookup.model_validate_json(
            (await client.get(f"/runs/{request.request_id}")).text
        )
        assert lookup.result == terminal.result
        path = Path("../.omo/evidence/essay-agent/task-7-sse-transcript.txt")
        await anyio.Path(path.parent).mkdir(parents=True, exist_ok=True)
        _ = await anyio.Path(path).write_text(response.text, encoding="utf-8")
        assert (await anyio.Path(path).stat()).st_size > 40
