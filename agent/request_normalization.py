"""Stable request identity and answer materialization from persisted raw inputs."""

import hashlib
import json
from dataclasses import dataclass
from uuid import uuid4

from .contracts import (
    EssayRequest,
    EvidenceVersion,
    QuestionKey,
    QuestionRegistryEntry,
    QuestionUpdate,
    RevisionContext,
    SourceHistory,
    SourceId,
    UserSource,
)
from .store_models import NormalizedInput, RunRecord, StoreConflictError


@dataclass(frozen=True, slots=True)
class NormalizationBasis:
    """Only server-loaded records can supply response IDs and historical context."""

    parent: RunRecord | None
    existing: RunRecord | None
    ancestors: tuple[EssayRequest, ...] = ()


def restore_identity(request: EssayRequest, existing: RunRecord | None) -> EssayRequest:
    """Restore omitted generated IDs before comparing canonical fingerprints."""
    if existing is None:
        return request
    return request.model_copy(
        update={
            "document_id": request.document_id
            if "document_id" in request.model_fields_set
            else existing.input.document_id,
            "thread_id": request.thread_id
            if "thread_id" in request.model_fields_set
            else existing.input.thread_id,
        }
    )


def fingerprint(request: EssayRequest) -> str:
    """Hash full normalized input except its idempotency key; preserve source text."""
    data = request.model_dump(mode="json", exclude={"request_id"})
    canonical = json.dumps(data, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def raw_sources(request: EssayRequest) -> tuple[UserSource, ...]:
    """Keep applicant and external form source IDs raw until the graph boundary."""
    return (*request.experiences, *request.user_views, *request.company_sources)


def source_texts(request: EssayRequest) -> dict[SourceId, str]:
    """Map form source IDs once and reserve a disjoint namespace for fields."""
    result = {SourceId(f"user:{source.source_id}"): source.text for source in raw_sources(request)}
    fields = {
        "job_posting": request.job_posting_text,
        "company_name": request.company_name,
        "job_title": request.job_title,
        "question": request.question,
    }
    result.update(
        {SourceId(f"field:{key}"): text for key, text in fields.items() if text is not None}
    )
    return result


def _updates(request: EssayRequest) -> tuple[QuestionUpdate, ...]:
    updates: dict[QuestionKey, QuestionUpdate] = {}
    for update in request.question_updates:
        normalized = (
            update if update.response_kind == "answer" else update.model_copy(update={"text": None})
        )
        previous = updates.get(update.question_key)
        if previous is not None and previous != normalized:
            code = "conflicting_question_updates"
            raise StoreConflictError(code)
        updates[update.question_key] = normalized
    return tuple(updates.values())


def _answer_source(
    entry: QuestionRegistryEntry,
    inputs: tuple[EssayRequest, ...],
    occupied: set[SourceId],
) -> SourceId:
    for request in inputs:
        for source in raw_sources(request):
            if SourceId(f"user:{source.source_id}") == entry.user_response_source_id:
                return source.source_id
    candidate = SourceId(str(uuid4()))
    while candidate in occupied:
        candidate = SourceId(str(uuid4()))
    return candidate


def normalize_request(
    request: EssayRequest, basis: NormalizationBasis, evidence: EvidenceVersion
) -> NormalizedInput:
    """Materialize explicit answers once; historical links alone never add evidence."""
    current = restore_identity(request, basis.existing)
    sources = raw_sources(current)
    if len({source.source_id for source in sources}) != len(sources):
        code = "duplicate_source_id"
        raise StoreConflictError(code)
    prior = (
        basis.parent.revision_context
        if basis.parent
        else RevisionContext(source_history=(), question_registry=())
    )
    registry = {entry.question_key: entry for entry in prior.question_registry}
    identities = (
        {entry.question_key: entry for entry in basis.existing.revision_context.question_registry}
        if basis.existing
        else registry
    )
    inputs = (current, *((basis.existing.input,) if basis.existing else ()), *basis.ancestors)
    occupied = {source.source_id for item in inputs for source in raw_sources(item)}
    experiences = {source.source_id: source for source in current.experiences}
    updates = _updates(current)
    for update in updates:
        entry = registry.get(update.question_key)
        if entry is None:
            code = "unknown_question_key"
            raise StoreConflictError(code)
        if update.response_kind == "answer":
            raw_id = _answer_source(identities.get(entry.question_key, entry), inputs, occupied)
            if raw_id in {
                source.source_id for source in (*current.user_views, *current.company_sources)
            }:
                code = "answer_source_category"
                raise StoreConflictError(code)
            if update.text is None:
                code = "answer_text_missing"
                raise StoreConflictError(code)
            experiences[raw_id] = UserSource(source_id=raw_id, text=update.text)
            occupied.add(raw_id)
            registry[entry.question_key] = entry.model_copy(
                update={
                    "user_response_source_id": SourceId(f"user:{raw_id}"),
                    "question_status": "asked",
                }
            )
        else:
            registry[entry.question_key] = entry.model_copy(
                update={"question_status": update.response_kind}
            )
    current = current.model_copy(
        update={"experiences": tuple(experiences.values()), "question_updates": updates}
    )
    old = source_texts(basis.parent.input) if basis.parent else {}
    new = source_texts(current)
    changes = tuple(
        SourceHistory(
            source_id=key,
            previous_text=old.get(key),
            current_text=new.get(key),
            status="removed"
            if key not in new
            else "superseded"
            if key in old and old[key] != new[key]
            else "active",
            evidence_version=evidence,
        )
        for key in dict.fromkeys((*old, *new))
    )
    return NormalizedInput(
        request=current,
        revision_context=RevisionContext(
            source_history=prior.source_history + changes,
            question_registry=tuple(registry.values()),
        ),
    )
