from pathlib import Path
from typing import Literal
from uuid import uuid4

import pytest

from agent import contracts as c
from agent.api_models import ChatResponse, ErrorResponse, RunLookup
from tests.api_adversarial_revisions import check_answer_identity, check_revision_history
from tests.api_adversarial_support import (
    Fault,
    events,
    record,
    request,
    session,
)


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.mark.anyio
@pytest.mark.parametrize("fault", ["failed", "unknown", "committed"])
@pytest.mark.parametrize("transport", ["json", "sse"])
async def test_save_fault_preserves_real_generated_result(
    tmp_path: Path, fault: Fault, transport: Literal["json", "sse"]
) -> None:
    # Given an actual full fake graph and a store fault after generation.
    async with session(tmp_path, fault) as current:
        form = request()
        # When the public endpoint executes the request and attempts its SQLite save.
        reply = await current.client.post(
            "/chat" if transport == "json" else "/chat/stream", json=form.model_dump(mode="json")
        )
        record(f"save-{fault}-{transport}", current, reply)
        # Then one successful generated result survives independently of persistence.
        assert reply.status_code == 200
        if transport == "json":
            envelope = ChatResponse.model_validate_json(reply.text)
            result, status = envelope.result, envelope.metadata.persistence_status
        else:
            stream = events(reply)
            assert not any(isinstance(event, c.RunError) for event in stream)
            terminal = stream[-1]
            assert isinstance(terminal, c.FinalResult)
            result, status = terminal.result, terminal.persistence_status
        assert status == ("stored" if fault == "committed" else fault)
        assert [item.model_dump(mode="json") for item in current.store.attempted] == [
            result.model_dump(mode="json")
        ]
        assert form.experiences[0].text in result.body
        assert result.request_id == form.request_id
        assert current.responses.calls == [
            "analyze_context",
            "plan_structure",
            "write_sections",
            "integrate_draft",
            "title_and_review",
        ]
        lookup = await current.client.get(f"/runs/{form.request_id}")
        duplicate = await current.client.post("/chat", json=form.model_dump(mode="json"))
        record(f"save-{fault}-{transport}-lookup", current, lookup, duplicate)
        if fault == "committed":
            assert lookup.status_code == duplicate.status_code == 200
            assert RunLookup.model_validate_json(lookup.text).result == result
            assert ChatResponse.model_validate_json(duplicate.text).result == result
        elif fault == "failed":
            assert lookup.status_code == 200
            unsaved = RunLookup.model_validate_json(lookup.text)
            assert unsaved.status == "interrupted"
            assert unsaved.result is None
            assert unsaved.error is not None
            assert unsaved.error.code == "interrupted"
            assert duplicate.status_code == 409
        else:
            assert lookup.status_code == 503
            assert duplicate.status_code == 409
        assert len(current.responses.calls) == 5


@pytest.mark.anyio
async def test_replay_uses_no_models_but_identity_and_input_changes_conflict(
    tmp_path: Path,
) -> None:
    # Given a completed graph result with omitted server-generated document/thread IDs.
    async with session(tmp_path) as current:
        form = request().model_dump(mode="json", exclude={"document_id", "thread_id"})
        original = await current.client.post("/chat", json=form)
        assert original.status_code == 200
        saved = ChatResponse.model_validate_json(original.text).result
        calls = len(current.responses.calls)
        # When both transports replay it, then exact stored identity/body require no LLM calls.
        replay = await current.client.post("/chat", json=form)
        stream = await current.client.post("/chat/stream", json=form)
        lookup = await current.client.get(f"/runs/{saved.request_id}")
        record("replay", current, original, replay, stream, lookup)
        assert ChatResponse.model_validate_json(replay.text).result == saved
        terminal = events(stream)[-1]
        assert isinstance(terminal, c.FinalResult)
        assert terminal.result == saved
        assert RunLookup.model_validate_json(lookup.text).result == saved
        assert len(current.responses.calls) == calls
        # When identity or content changes, then replay is rejected before any new generation.
        for key, value in (
            ("document_id", str(uuid4())),
            ("thread_id", str(uuid4())),
            ("parent_version_id", saved.version_id),
            ("tone", "차분한 문체"),
        ):
            conflict = await current.client.post("/chat", json={**form, key: value})
            record(f"conflict-{key}", current, conflict)
            assert conflict.status_code == 409
            assert (
                ErrorResponse.model_validate_json(conflict.text).error.request_id
                == saved.request_id
            )
            error = ErrorResponse.model_validate_json(conflict.text).error
            assert error.code == "request_hash_conflict"
            assert len(current.responses.calls) == calls


@pytest.mark.anyio
@pytest.mark.parametrize("transport", ["json", "sse"])
async def test_execution_error_matches_saved_and_replayed_envelope(
    tmp_path: Path, transport: Literal["json", "sse"]
) -> None:
    # Given storage admission succeeds but loading the runtime parent fails.
    async with session(tmp_path, "workflow") as current:
        form = request()
        # When the workflow fails after admission through either public transport.
        reply = await current.client.post(
            "/chat" if transport == "json" else "/chat/stream", json=form.model_dump(mode="json")
        )
        if transport == "json":
            assert reply.status_code == 500
            error = ErrorResponse.model_validate_json(reply.text).error
        else:
            terminal = events(reply)[-1]
            assert isinstance(terminal, c.RunError)
            error = terminal.error
        lookup = await current.client.get(f"/runs/{form.request_id}")
        duplicate = await current.client.post("/chat/stream", json=form.model_dump(mode="json"))
        record(f"error-{transport}", current, reply, lookup, duplicate)
        # Then the common error survives GET and pre-stream duplicate admission unchanged.
        assert error.request_id == form.request_id
        assert error.code == "workflow_failed"
        assert error.generation_status == "technical_error"
        assert error.last_result is None
        assert lookup.status_code == 200
        run = RunLookup.model_validate_json(lookup.text)
        assert run.status == "failed"
        assert run.result is None
        assert run.error == error
        assert duplicate.status_code == 409
        assert ErrorResponse.model_validate_json(duplicate.text).error == error
        assert not current.responses.calls


@pytest.mark.anyio
@pytest.mark.parametrize("correction", ["still_missing", "now_supported"])
async def test_unavailable_survives_style_revision_and_corrected_source_history(
    tmp_path: Path, correction: Literal["still_missing", "now_supported"]
) -> None:
    await check_revision_history(tmp_path, correction)


@pytest.mark.anyio
async def test_answer_source_id_is_reused_without_duplicate_evidence(tmp_path: Path) -> None:
    await check_answer_identity(tmp_path)
