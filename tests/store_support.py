from uuid import uuid4

from agent.contracts import (
    EssayRequest,
    EssayResult,
    QuestionKey,
    QuestionRegistryEntry,
    QuestionUpdate,
    SourceId,
    UserSource,
    VersionId,
)
from agent.session_store import SqliteSessionStore
from agent.store_models import RunRecord
from tests.fixtures.cases import ContractCase


def make_result(record: RunRecord) -> EssayResult:
    result = ContractCase.load("complete.json").parse().result
    assert result is not None
    return result.model_copy(
        update={
            "request_id": record.input.request_id,
            "document_id": record.input.document_id,
            "evidence_version": record.evidence_version,
            "version_id": VersionId(str(uuid4())),
        }
    )


def complete(store: SqliteSessionStore, record: RunRecord) -> EssayResult:
    result = make_result(record)
    store.save_result(record, result, record.revision_context)
    return result


def question_parent(store: SqliteSessionStore) -> RunRecord:
    record = store.reserve(
        EssayRequest(experiences=(UserSource(source_id=SourceId("a"), text="원문"),))
    ).record
    revision = record.revision_context.model_copy(
        update={
            "question_registry": (
                QuestionRegistryEntry(
                    question_key=QuestionKey("q1"),
                    subject_source_ids=(SourceId("user:a"),),
                    missing_detail="배운 점",
                    question_status="asked",
                    user_response_source_id=None,
                ),
            )
        }
    )
    store.save_result(record, make_result(record), revision)
    saved = store.get(record.input.request_id)
    assert saved is not None
    assert saved.result is not None
    return saved


def revision_request(parent: RunRecord, *, answer: str | None = None) -> EssayRequest:
    assert parent.result is not None
    return EssayRequest(
        document_id=parent.input.document_id,
        thread_id=parent.input.thread_id,
        parent_version_id=parent.result.version_id,
        experiences=parent.input.experiences,
        question_updates=()
        if answer is None
        else (QuestionUpdate(question_key=QuestionKey("q1"), response_kind="answer", text=answer),),
    )
