"""Preserve question lineage while recording the final run's visible guidance."""

from .contracts import Gap, QuestionKey, QuestionRegistryEntry, RevisionContext, SourceId
from .graph_state import EssayState


def _subjects(gap: Gap, state: EssayState) -> tuple[SourceId, ...]:
    analysis = state.get("analysis")
    candidates = () if analysis is None else analysis.answer_candidates
    candidate = next((item for item in candidates if item.candidate_id == gap.candidate_id), None)
    subjects = tuple(
        dict.fromkeys(
            fact.source_id
            for fact in state.get("facts", ())
            if fact.source_kind == "applicant"
            and (candidate is None or fact.fact_id in candidate.fact_ids)
        )
    )
    if not subjects and gap.candidate_id is None:
        subjects = tuple(
            source.source_id
            for source in state.get("sources", ())
            if source.source_kind == "applicant"
        )
    return subjects


def final_revision(state: EssayState) -> RevisionContext:
    """Preserve interaction status and accept current evidence-based resolutions."""
    prior = state["revision_context"]
    registry: dict[QuestionKey, QuestionRegistryEntry] = {
        entry.question_key: entry for entry in prior.question_registry
    }
    analysis, result = state.get("analysis"), state.get("result")
    if analysis is None or result is None:
        return prior
    for gap in analysis.gaps:
        existing = registry.get(gap.question_key)
        status = gap.question_status
        if (
            status != "resolved"
            and existing is not None
            and existing.question_status in ("unavailable", "not_needed")
        ):
            status = existing.question_status
        elif status in ("proposed", "asked"):
            status = "asked" if existing and existing.question_status == "asked" else "proposed"
        registry[gap.question_key] = (
            existing.model_copy(update={"question_status": status})
            if existing is not None
            else QuestionRegistryEntry(
                question_key=gap.question_key,
                subject_source_ids=_subjects(gap, state),
                missing_detail=gap.missing_detail,
                question_status=status,
                user_response_source_id=None,
            )
        )
    for suggestion in result.suggestions:
        key = suggestion.question_key
        if key is None or key in registry:
            continue
        subjects = tuple(
            source.source_id
            for source in state.get("sources", ())
            if source.source_kind == "applicant"
        )
        registry[key] = QuestionRegistryEntry(
            question_key=key,
            subject_source_ids=subjects,
            missing_detail=suggestion.missing_detail,
            question_status="proposed"
            if suggestion.question_status == "asked"
            else suggestion.question_status,
            user_response_source_id=None,
        )
    return prior.model_copy(update={"question_registry": tuple(registry.values())})
