import sqlite3
from pathlib import Path
from time import monotonic

import anyio
import pytest

from agent.api_models import ChatResponse
from agent.contracts import EssayRequest
from tests.api_support import client_for


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


def hold_writer(path: Path) -> sqlite3.Connection:
    connection = sqlite3.connect(path, check_same_thread=False)
    _ = connection.execute("BEGIN IMMEDIATE")
    return connection


@pytest.mark.anyio
async def test_sqlite_writer_contention_does_not_block_health(tmp_path: Path) -> None:
    path = tmp_path / "contended.db"
    async with client_for(path) as client:
        connection = await anyio.to_thread.run_sync(hold_writer, path)
        started = anyio.Event()
        results: list[ChatResponse] = []

        async def submit() -> None:
            started.set()
            response = await client.post("/chat", content=EssayRequest().model_dump_json())
            assert response.status_code == 200
            results.append(ChatResponse.model_validate_json(response.text))

        try:
            async with anyio.create_task_group() as group:
                begin = monotonic()
                _ = group.start_soon(submit)
                await started.wait()
                await anyio.sleep(0.05)
                response = await client.get("/health")
                assert response.status_code == 200
                assert monotonic() - begin < 0.5
                assert not results
                await anyio.to_thread.run_sync(connection.rollback)
        finally:
            await anyio.to_thread.run_sync(connection.close)
        assert len(results) == 1
