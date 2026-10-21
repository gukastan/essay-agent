"""Bind follow-up identities to evidence subjects and server-owned history."""

from uuid import NAMESPACE_URL, uuid5

from .contracts import Gap, QuestionKey, SourceId
from .stage_analysis_models import AnalysisOutput, AnalysisPayload
from .stage_evidence import eligible_links


def normalize_gap(gap: Gap, output: AnalysisOutput, payload: AnalysisPayload) -> Gap:
    """Reuse registry status only for the same source subjects and missing detail."""
    candidate = next(
        (
            item
            for item in output.analysis.answer_candidates
            if item.candidate_id == gap.candidate_id
        ),
        None,
    )
    subjects = frozenset(
        fact.source_id
        for fact in output.facts
        if fact.source_kind == "applicant"
        and (candidate is None or fact.fact_id in candidate.fact_ids)
    )
    if not subjects and gap.candidate_id is None:
        subjects = frozenset(s.source_id for s in payload.sources if s.source_kind == "applicant")
    prior = next(
        (
            entry
            for entry in payload.revision_context.question_registry
            if frozenset(entry.subject_source_ids) == subjects
            and (
                entry.question_key == gap.question_key
                or entry.missing_detail.strip() == gap.missing_detail.strip()
            )
        ),
        None,
    )
    key = prior.question_key if prior else new_question_key(gap, payload, subjects)
    status = "proposed"
    if prior and prior.question_status in ("asked", "unavailable", "not_needed"):
        status = prior.question_status
    supported = any(
        link.requirement_id in gap.requirement_ids
        and (gap.candidate_id is None or link.candidate_id == gap.candidate_id)
        for link in eligible_links(output.analysis, output.facts)
    )
    if supported and gap.question_status == "resolved":
        status = "resolved"
    return gap.model_copy(
        update={
            "question_key": key,
            "question_status": status,
            "question": None
            if status in ("unavailable", "not_needed", "resolved")
            else gap.question,
        }
    )


def new_question_key(
    gap: Gap, payload: AnalysisPayload, subjects: frozenset[SourceId]
) -> QuestionKey:
    """Keep stable keys across style changes without conflating different sources."""
    identity = f"{payload.request.document_id}:{sorted(subjects)}:{gap.missing_detail}"
    return QuestionKey(str(uuid5(NAMESPACE_URL, identity)))
