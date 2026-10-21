from pathlib import Path
from uuid import uuid4

import anyio
import pytest
from pydantic import TypeAdapter

from agent.api_models import ChatResponse, ErrorResponse, HealthResponse, RunLookup, VersionList
from agent.contracts import EssayRequest, FinalResult
from agent.run_channels import RunEvent
from tests.api_support import Providers, client_for

pytestmark = pytest.mark.anyio


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


def parse_events(text: str) -> tuple[RunEvent, ...]:
    return tuple(
        TypeAdapter(RunEvent).validate_json(line.removeprefix("data: "))
        for line in text.splitlines()
        if line.startswith("data: ") and line != "data: [DONE]"
    )


async def test_json_sse_lookup_replay_identical(tmp_path: Path) -> None:
    providers = Providers()
    request = EssayRequest()
    async with client_for(tmp_path / "api.db", providers.factories()) as client:
        stream = await client.post("/chat/stream", content=request.model_dump_json())
        assert stream.status_code == 200
        events = parse_events(stream.text)
        terminal = events[-1]
        assert isinstance(terminal, FinalResult)
        assert terminal.persistence_status == "stored"
        assert len(events) == 13
        assert [event.stage for event in events if event.event == "StageStarted"] == [
            1,
            2,
            3,
            4,
            5,
            6,
        ]
        assert stream.text.endswith("data: [DONE]\n\n")
        lookup = RunLookup.model_validate_json(
            (await client.get(f"/runs/{request.request_id}")).text
        )
        assert lookup.result == terminal.result
        replay = ChatResponse.model_validate_json(
            (await client.post("/chat", content=request.model_dump_json())).text
        )
        assert replay.result == terminal.result
        assert len(providers.fast.calls) == 2
        assert len(providers.quality.calls) == 3
        versions = VersionList.model_validate_json(
            (await client.get(f"/documents/{request.document_id}/versions")).text
        )
        assert len(versions.versions) == 1
        assert lookup.input == request
        assert "raw" not in replay.model_dump()
    assert providers.fast.closed
    assert providers.quality.closed


async def test_slow_generation_keeps_health_responsive_and_duplicate_conflicts(
    tmp_path: Path,
) -> None:
    providers = Providers()
    providers.fast.slow = True
    request = EssayRequest()
    results: list[ChatResponse] = []
    async with client_for(tmp_path / "slow.db", providers.factories()) as client:

        async def submit() -> None:
            response = await client.post("/chat", content=request.model_dump_json())
            results.append(ChatResponse.model_validate_json(response.text))

        async with anyio.create_task_group() as group:
            _ = group.start_soon(submit)
            await providers.fast.entered.wait()
            with anyio.fail_after(1):
                health = HealthResponse.model_validate_json((await client.get("/health")).text)
                duplicate = await client.post("/chat/stream", content=request.model_dump_json())
            assert health.active_runs == 1
            assert duplicate.status_code == 409
            assert duplicate.headers["location"] == f"/runs/{request.request_id}"
            assert duplicate.headers["content-type"].startswith("application/json")
            providers.fast.release.set()
        assert len(results) == 1
        assert len(providers.fast.calls) == 2


async def test_validation_is_safe_before_stream_and_empty_input_works(tmp_path: Path) -> None:
    async with client_for(tmp_path / "validation.db") as client:
        request_id = uuid4()
        bad = await client.post(
            "/chat/stream",
            json={"request_id": str(request_id), "previous_draft": "private forbidden content"},
        )
        error = ErrorResponse.model_validate_json(bad.text)
        assert bad.status_code == 422
        assert error.error.request_id == request_id
        assert "private forbidden content" not in bad.text
        malformed = await client.post("/chat", content="invalid JSON")
        assert malformed.status_code == 422
        assert ErrorResponse.model_validate_json(malformed.text).error.request_id is None
        missing = await client.get(f"/runs/{uuid4()}")
        assert missing.status_code == 404
        assert ErrorResponse.model_validate_json(missing.text).error.code == "run_not_found"
        empty = await client.post("/chat", json={})
        assert empty.status_code == 200
        assert ChatResponse.model_validate_json(empty.text).result.body
