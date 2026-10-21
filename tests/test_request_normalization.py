import pytest

from agent.contracts import EssayRequest, QuestionKey, QuestionUpdate, SourceId, UserSource
from agent.session_store import SqliteSessionStore
from agent.store_models import ReservationKind, StoreConflictError
from tests.store_support import complete, make_result, question_parent, revision_request

pytest_plugins = ("tests.store_fixtures",)


def test_answer_normalization_replay_and_correction(store: SqliteSessionStore) -> None:
    parent = question_parent(store)
    incoming = revision_request(parent, answer="직접 배운 점")
    record = store.reserve(incoming).record
    assert len(record.input.experiences) == 2
    response = record.input.experiences[-1]
    assert (
        record.revision_context.question_registry[0].user_response_source_id
        == f"user:{response.source_id}"
    )
    assert store.reserve(incoming).record.input == record.input
    _ = complete(store, record)
    saved = store.get(record.input.request_id)
    assert saved is not None
    unchanged = store.reserve(revision_request(saved, answer="직접 배운 점")).record
    assert unchanged.input.experiences == record.input.experiences
    corrected = store.reserve(revision_request(saved, answer="정정한 배움")).record
    assert corrected.input.experiences[-1].source_id == response.source_id
    assert corrected.input.experiences[-1].text == "정정한 배움"
    assert any(
        item.previous_text == "직접 배운 점" and item.current_text == "정정한 배움"
        for item in corrected.revision_context.source_history
    )


def test_removed_answer_history_does_not_reactivate_source(store: SqliteSessionStore) -> None:
    parent = question_parent(store)
    answered = store.reserve(revision_request(parent, answer="answer")).record
    _ = complete(store, answered)
    saved = store.get(answered.input.request_id)
    assert saved is not None
    request = revision_request(saved).model_copy(
        update={"experiences": (), "revision_instruction": "문체만 수정"}
    )
    removed = store.reserve(request).record
    assert removed.input.experiences == ()
    assert removed.revision_context.question_registry[0].user_response_source_id is not None
    assert any(
        item.status == "removed" and item.previous_text == "answer"
        for item in removed.revision_context.source_history
    )


@pytest.mark.parametrize("kind", ["unavailable", "not_needed"])
def test_nonanswer_status_never_creates_source(store: SqliteSessionStore, kind: str) -> None:
    parent = question_parent(store)
    update = QuestionUpdate.model_validate(
        {"question_key": "q1", "response_kind": kind, "text": None}
    )
    request = revision_request(parent).model_copy(update={"question_updates": (update,)})
    record = store.reserve(request).record
    assert record.input.experiences == parent.input.experiences
    assert record.revision_context.question_registry[0].question_status == kind


def test_namespace_and_original_text_preserved(store: SqliteSessionStore) -> None:
    sources = tuple(
        UserSource(source_id=SourceId(key), text=" 원문\r\n🙂 ")
        for key in ("field:job_posting", "mcp:any", "user:any")
    )
    record = store.reserve(EssayRequest(experiences=sources, job_posting_text="공고")).record
    assert record.input.experiences == sources
    assert {item.source_id for item in record.revision_context.source_history} == {
        "user:field:job_posting",
        "user:mcp:any",
        "user:user:any",
        "field:job_posting",
    }
    assert "previous_draft" not in record.input.model_dump()


def test_duplicate_unknown_questions_and_source_ids_rejected(store: SqliteSessionStore) -> None:
    parent = question_parent(store)
    unknown = QuestionUpdate(
        question_key=QuestionKey("unknown"), response_kind="unavailable", text=None
    )
    with pytest.raises(StoreConflictError, match="unknown_question_key"):
        _ = store.reserve(
            revision_request(parent).model_copy(update={"question_updates": (unknown,)})
        )
    request = revision_request(parent, answer="one")
    conflict = QuestionUpdate(question_key=QuestionKey("q1"), response_kind="answer", text="two")
    with pytest.raises(StoreConflictError, match="conflicting_question_updates"):
        _ = store.reserve(
            request.model_copy(update={"question_updates": (*request.question_updates, conflict)})
        )
    duplicate = UserSource(source_id=SourceId("a"), text="duplicate")
    with pytest.raises(StoreConflictError, match="duplicate_source_id"):
        _ = store.reserve(request.model_copy(update={"user_views": (duplicate,)}))


def test_removed_answer_can_be_explicitly_reintroduced_with_historical_id(
    store: SqliteSessionStore,
) -> None:
    parent = question_parent(store)
    answered = store.reserve(revision_request(parent, answer="answer")).record
    raw_id = answered.input.experiences[-1].source_id
    _ = complete(store, answered)
    saved = store.get(answered.input.request_id)
    assert saved is not None
    removed = store.reserve(revision_request(saved).model_copy(update={"experiences": ()})).record
    _ = complete(store, removed)
    saved_removed = store.get(removed.input.request_id)
    assert saved_removed is not None
    returned = store.reserve(revision_request(saved_removed, answer="answer")).record
    assert returned.input.experiences == (UserSource(source_id=raw_id, text="answer"),)


def test_exact_duplicate_answers_normalize_once(store: SqliteSessionStore) -> None:
    parent = question_parent(store)
    request = revision_request(parent, answer="answer")
    repeated = request.model_copy(update={"question_updates": request.question_updates * 2})
    record = store.reserve(repeated).record
    assert len(record.input.experiences) == 2
    assert len(record.input.question_updates) == 1
    assert store.reserve(request).kind == ReservationKind.RUNNING


def test_final_registry_cannot_erase_previous_question(store: SqliteSessionStore) -> None:
    parent = question_parent(store)
    record = store.reserve(revision_request(parent, answer="answer")).record
    revision = record.revision_context.model_copy(update={"question_registry": ()})
    with pytest.raises(StoreConflictError, match="question_history_immutable"):
        store.save_result(record, make_result(record), revision)


def test_same_request_changed_source_whitespace_conflicts(store: SqliteSessionStore) -> None:
    request = EssayRequest(experiences=(UserSource(source_id=SourceId("a"), text=" text "),))
    _ = store.reserve(request)
    changed = request.model_copy(
        update={"experiences": (UserSource(source_id=SourceId("a"), text="text"),)}
    )
    with pytest.raises(StoreConflictError, match="request_hash_conflict"):
        _ = store.reserve(changed)
