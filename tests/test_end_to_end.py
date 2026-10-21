import time
from pathlib import Path
from uuid import uuid4

import pytest

from agent.api_models import ChatResponse, ErrorResponse, RunLookup
from agent.contracts import EssayRequest, FinalResult, StageCompleted
from tests.e2e_processes import record, running
from tests.e2e_server import Mode
from tests.e2e_trace import validate_trace
from tests.test_api_http import parse_events


def sparse() -> EssayRequest:
    return EssayRequest.model_validate_json(Path("tests/fixtures/sparse_request.json").read_text())


def test_backend_proxy_stdio_and_sqlite_restart(tmp_path: Path) -> None:
    database = tmp_path / "restart.db"
    request = sparse()
    with running(database, "normal", "normal") as stack:
        assert stack.client.get("/").status_code == 200
        reply = stack.client.post("/chat", content=request.model_dump_json())
        record("task-10-http.json", reply)
        assert reply.status_code == 200
        first = ChatResponse.model_validate_json(reply.text)
        assert first.metadata.persistence_status == "stored"
        assert request.experiences[0].text in first.result.body
        validate_trace(stack.directory, first.result)
        stream = stack.client.post("/chat/stream", json={})
        record("task-10-stream.txt", stream)
        terminal = parse_events(stream.text)[-1]
        assert isinstance(terminal, FinalResult)
        assert terminal.result.body
    with running(database, "normal", "restart") as stack:
        lookup = stack.client.get(f"/runs/{request.request_id}")
        record("task-10-restart.json", lookup)
        assert RunLookup.model_validate_json(lookup.text).result == first.result
        replay = stack.client.post("/chat", content=request.model_dump_json())
        assert ChatResponse.model_validate_json(replay.text).result == first.result
        assert not tuple(stack.directory.glob("*-payload.json"))


@pytest.mark.parametrize(
    ("mode", "nodes"),
    [
        ("normal", 6),
        ("repair1", 8),
        ("repair2", 10),
        ("analysis", 6),
        ("title", 6),
        ("repair", 8),
        ("failed", 6),
        ("unknown", 6),
    ],
)
def test_full_process_failure_and_repair_paths(tmp_path: Path, mode: Mode, nodes: int) -> None:
    with running(tmp_path / "scenario.db", mode, f"scenario-{mode}") as stack:
        reply = stack.client.post("/chat/stream", content=sparse().model_dump_json())
        record(f"task-10-scenario-{mode}.txt", reply)
        assert reply.status_code == 200
        events = parse_events(reply.text)
        assert len([event for event in events if isinstance(event, StageCompleted)]) == nodes
        terminal = events[-1]
        assert isinstance(terminal, FinalResult)
        assert terminal.result.body
        assert terminal.persistence_status == (mode if mode in ("failed", "unknown") else "stored")


def test_disconnect_duplicate_and_interrupted_restart(tmp_path: Path) -> None:
    database = tmp_path / "interrupted.db"
    request = sparse()
    with running(database, "slow", "interrupted") as stack:
        with stack.client.stream(
            "POST", "/chat/stream", content=request.model_dump_json()
        ) as response:
            assert response.status_code == 200
            for line in response.iter_lines():
                if "StageStarted" in line:
                    break
        duplicate = stack.client.post("/chat", content=request.model_dump_json())
        assert duplicate.status_code == 409
        stack.backend.child.kill()
        _ = stack.backend.child.wait(timeout=5)
    with running(database, "normal", "interrupted-restart") as stack:
        lookup = stack.client.get(f"/runs/{request.request_id}")
        record("task-10-interrupted.txt", lookup)
        assert RunLookup.model_validate_json(lookup.text).status == "interrupted"
        time.sleep(0.1)
        assert not tuple(stack.directory.glob("*-payload.json"))
        assert stack.client.post("/chat", content=request.model_dump_json()).status_code == 409


def test_workflow_error_retains_actual_persisted_parent(tmp_path: Path) -> None:
    database = tmp_path / "last-result.db"
    request = sparse()
    with running(database, "normal", "prior-result") as stack:
        first = ChatResponse.model_validate_json(
            stack.client.post("/chat", content=request.model_dump_json()).text
        ).result
    revision = request.model_copy(
        update={"request_id": uuid4(), "parent_version_id": first.version_id}
    )
    with running(database, "execution", "prior-result-failure") as stack:
        reply = stack.client.post("/chat", content=revision.model_dump_json())
        record("task-10-prior-result-error.json", reply)
        assert reply.status_code == 500
        error = ErrorResponse.model_validate_json(reply.text).error
        assert error.last_result == first
        lookup = RunLookup.model_validate_json(
            stack.client.get(f"/runs/{revision.request_id}").text
        )
        assert lookup.error == error
        assert "Synthetic workflow failure" not in reply.text
