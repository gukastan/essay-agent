import sqlite3
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from uuid import uuid4

import pytest
from typing_extensions import override

from agent.contracts import (
    EssayRequest,
    EssayResult,
    RevisionContext,
    RunErrorPayload,
    SourceId,
    UserSource,
)
from agent.session_store import SqliteSessionStore
from agent.store_models import ReservationKind, RunRecord, StoreConflictError, StoreUnavailableError
from tests.store_support import complete, make_result, question_parent, revision_request

pytest_plugins = ("tests.store_fixtures",)


def test_messages_survive_reopen(tmp_path: Path) -> None:
    path = tmp_path / "test.db"
    legacy = sqlite3.connect(path)
    _ = legacy.execute(
        "CREATE TABLE messages (thread_id TEXT, role TEXT, content TEXT, created TEXT)"
    )
    _ = legacy.execute(
        "INSERT INTO messages VALUES (?,?,?,?)", ("thread", "user", "original message", "before")
    )
    legacy.commit()
    legacy.close()
    first = SqliteSessionStore(path)
    first.append("other", "assistant", "separate thread")
    assert first.load("other") == [{"role": "assistant", "content": "separate thread"}]
    first.close()
    second = SqliteSessionStore(path)
    try:
        assert second.load("thread") == [{"role": "user", "content": "original message"}]
        _ = second.reserve(EssayRequest())
        assert second.load("thread") == [{"role": "user", "content": "original message"}]
    finally:
        second.close()


def test_completed_request_replay_and_omitted_ids(store: SqliteSessionStore) -> None:
    request = EssayRequest(question="원문\n  보존")
    record = store.reserve(request).record
    result = complete(store, record)
    replay = EssayRequest(request_id=request.request_id, question=request.question)
    reserved = store.reserve(replay)
    assert reserved.kind == ReservationKind.REPLAY
    assert reserved.record.result == result
    assert reserved.record.input.document_id == request.document_id
    assert reserved.record.input.thread_id == request.thread_id
    assert store.get(request.request_id) == reserved.record


@pytest.mark.parametrize(
    "field", ["document_id", "thread_id", "question", "tone", "revision_instruction"]
)
def test_request_hash_conflicts(store: SqliteSessionStore, field: str) -> None:
    request = EssayRequest(question="original")
    _ = store.reserve(request)
    changed = request.model_copy(update={field: uuid4() if field.endswith("_id") else "changed"})
    with pytest.raises(StoreConflictError, match="request_hash_conflict"):
        _ = store.reserve(changed)


def test_concurrent_duplicate_reservation_across_connections(tmp_path: Path) -> None:
    path = tmp_path / "race.db"
    stores = (SqliteSessionStore(path), SqliteSessionStore(path))
    request = EssayRequest()
    try:
        with ThreadPoolExecutor(max_workers=2) as executor:
            futures = tuple(executor.submit(value.reserve, request) for value in stores)
            kinds = [future.result().kind for future in futures]
        assert sorted(kinds) == sorted([ReservationKind.NEW, ReservationKind.RUNNING])
    finally:
        for value in stores:
            value.close()


def test_revision_keeps_prior_result_and_corrected_history(store: SqliteSessionStore) -> None:
    first = store.reserve(
        EssayRequest(experiences=(UserSource(source_id=SourceId("a"), text="before"),))
    ).record
    result = complete(store, first)
    request = EssayRequest(
        document_id=first.input.document_id,
        parent_version_id=result.version_id,
        experiences=(UserSource(source_id=SourceId("a"), text="after"),),
    )
    second = store.reserve(request).record
    change = second.revision_context.source_history[-1]
    assert (change.source_id, change.previous_text, change.current_text, change.status) == (
        "user:a",
        "before",
        "after",
        "superseded",
    )
    _ = complete(store, second)
    versions = store.versions(first.input.document_id)
    assert len(versions) == 2
    assert versions[0].result == result
    assert versions[0].input.experiences[0].text == "before"
    assert versions[1].input.experiences[0].text == "after"


def test_wrong_document_or_unsaved_parent_rejected(store: SqliteSessionStore) -> None:
    first = store.reserve(EssayRequest()).record
    unsaved = make_result(first)
    with pytest.raises(StoreConflictError, match="parent_not_persisted"):
        _ = store.reserve(
            EssayRequest(document_id=first.input.document_id, parent_version_id=unsaved.version_id)
        )
    result = complete(store, first)
    with pytest.raises(StoreConflictError, match="parent_not_persisted"):
        _ = store.reserve(EssayRequest(parent_version_id=result.version_id))


def test_completed_version_cannot_be_overwritten(store: SqliteSessionStore) -> None:
    record = store.reserve(EssayRequest()).record
    result = complete(store, record)
    store.save_result(record, result, record.revision_context)
    with pytest.raises(StoreConflictError, match="immutable"):
        store.save_result(
            record, result.model_copy(update={"body": "replacement"}), record.revision_context
        )
    saved = store.get(record.input.request_id)
    assert saved is not None
    assert saved.result == result


def test_restart_marks_only_orphan_running_interrupted(tmp_path: Path) -> None:
    path = tmp_path / "restart.db"
    first = SqliteSessionStore(path)
    record = first.reserve(EssayRequest()).record
    first.close()
    second = SqliteSessionStore(path)
    try:
        assert second.interrupt_orphans(frozenset({record.input.request_id})) == ()
        assert second.interrupt_orphans(frozenset()) == (record.input.request_id,)
        replay = second.reserve(record.input)
        assert replay.kind == ReservationKind.INTERRUPTED
        assert replay.record.error is not None
        assert replay.record.error.code == "interrupted"
    finally:
        second.close()


def test_saved_failure_preserves_last_result_and_never_restarts(store: SqliteSessionStore) -> None:
    record = store.reserve(EssayRequest()).record
    last = make_result(record)
    error = RunErrorPayload(
        request_id=record.input.request_id,
        generation_status="technical_error",
        code="workflow",
        message="작성 처리 오류",
        last_result=last,
    )
    store.save_error(record, error)
    assert store.reserve(record.input).kind == ReservationKind.FAILED
    saved = store.get(record.input.request_id)
    assert saved is not None
    assert saved.error == error
    assert store.versions(record.input.document_id) == ()


class UncertainStore(SqliteSessionStore):
    @override
    def save_result(
        self, record: RunRecord, result: EssayResult, revision: RevisionContext
    ) -> None:
        super().save_result(record, result, revision)
        raise StoreUnavailableError


def test_uncertain_save_reconciles_without_second_write(tmp_path: Path) -> None:
    store = UncertainStore(tmp_path / "uncertain.db")
    try:
        record = store.reserve(EssayRequest()).record
        result = make_result(record)
        assert store.reconcile_result(record, result) == "failed"
        with pytest.raises(StoreUnavailableError):
            store.save_result(record, result, record.revision_context)
        assert store.reconcile_result(record, result) == "stored"
        assert len(store.versions(record.input.document_id)) == 1
    finally:
        store.close()
    assert store.reconcile_result(record, result) == "unknown"


def test_corrupted_row_is_not_empty_success(store: SqliteSessionStore) -> None:
    record = store.reserve(EssayRequest()).record
    with store.database.transaction():
        _ = store.database.execute(
            "UPDATE essay_runs SET input_json='invalid' WHERE request_id=?",
            (str(record.input.request_id),),
        )
    with pytest.raises(StoreUnavailableError):
        _ = store.get(record.input.request_id)


def test_parent_omission_changes_request_identity(store: SqliteSessionStore) -> None:
    parent = question_parent(store)
    request = revision_request(parent)
    _ = store.reserve(request)
    with pytest.raises(StoreConflictError, match="request_hash_conflict"):
        _ = store.reserve(request.model_copy(update={"parent_version_id": None}))


def test_version_id_cannot_be_reused_in_other_run(store: SqliteSessionStore) -> None:
    first = store.reserve(EssayRequest()).record
    result = complete(store, first)
    second = store.reserve(EssayRequest()).record
    repeated = make_result(second).model_copy(update={"version_id": result.version_id})
    with pytest.raises(StoreConflictError, match="version_already_persisted"):
        store.save_result(second, repeated, second.revision_context)
    assert store.reconcile_result(first, result) == "stored"


def test_failed_write_leaves_visible_result_and_orphan_can_be_reconciled(
    store: SqliteSessionStore,
) -> None:
    record = store.reserve(EssayRequest()).record
    result = make_result(record)
    with store.database.transaction():
        _ = store.database.execute("""CREATE TRIGGER fail_completion
            BEFORE UPDATE OF result_json ON essay_runs
            BEGIN SELECT RAISE(ABORT, 'injected write failure'); END""")
    with pytest.raises(StoreUnavailableError):
        store.save_result(record, result, record.revision_context)
    assert result.body
    assert store.reconcile_result(record, result) == "failed"
    assert store.interrupt_orphans(frozenset()) == (record.input.request_id,)
    assert store.reserve(record.input).kind == ReservationKind.INTERRUPTED


def test_source_history_cannot_be_erased_during_save(store: SqliteSessionStore) -> None:
    record = store.reserve(EssayRequest(question="original")).record
    with pytest.raises(StoreConflictError, match="source_history_immutable"):
        store.save_result(
            record, make_result(record), RevisionContext(source_history=(), question_registry=())
        )
