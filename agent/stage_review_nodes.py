"""Review and repair graph nodes with bounded server-owned control."""

from __future__ import annotations

from typing import TYPE_CHECKING

from .composition_rules import new_version
from .contract_base import ContractViolation
from .contract_review_validation import MAX_REPAIRS
from .contracts import RepairLogEntry, validate_contract
from .essay_llm import GenerationError
from .review_normalization import normalize_review, review_context, unavailable_review
from .review_safety import safe_delivery_pair
from .review_selection import control_for, matching_pair, prefer_candidate
from .stage_composition_nodes import writing_payload
from .stage_issues import generation_issue
from .stage_review_models import RepairOutput, RepairPayload, ReviewOutput, ReviewPayload

if TYPE_CHECKING:
    from .deps import SupervisorDeps
    from .graph_state import EssayState, EssayUpdate


def review_payload(state: EssayState) -> ReviewPayload:
    """Load frozen sources and the current candidate; old reports remain historical clues."""
    writing, integration, bundle = (
        state.get("writing_report"),
        state.get("integration_report"),
        state.get("candidate_bundle"),
    )
    if writing is None or integration is None or bundle is None:
        code = "review_context"
        raise ContractViolation(code, "Review requires composition handoff")
    current = writing_payload(state)
    return ReviewPayload(
        request=current.request,
        evidence_version=current.evidence_version,
        sources=current.sources,
        facts=current.facts,
        analysis=current.analysis,
        outline=current.outline,
        fallback_provenance=state.get("fallback_provenance", ()),
        candidate_bundle=bundle,
        writing_report=writing,
        integration_report=integration,
        repair_count=state.get("repair_count", 0),
        stored_parent=state.get("stored_parent"),
    )


async def title_and_review(state: EssayState, deps: SupervisorDeps) -> EssayUpdate:
    """Perform one review or traverse a failed repair using the already-reviewed best pair."""
    payload = review_payload(state)
    count = state.get("repair_count", 0)
    log = state.get("repair_log", ())
    best, best_review = state.get("best_bundle"), state.get("best_review")
    issues = state.get("technical_issues", ())
    usage = state.get("usage", ())
    failed = bool(log and log[-1].outcome == "failed")
    if failed and matching_pair(best, best_review) and best is not None and best_review is not None:
        bundle, review = best, best_review
    else:
        try:
            generated = await deps.quality_llm.generate("title_and_review", payload, ReviewOutput)
            bundle, review = normalize_review(payload, generated.output)
            usage += (generated.usage,)
        except GenerationError as error:
            failed = True
            issues += (generation_issue("title_and_review", error),)
            usage += (error.usage,)
            if matching_pair(best, best_review) and best is not None and best_review is not None:
                bundle, review = best, best_review
            else:
                bundle, review = unavailable_review(payload, replace_body=True)
    no_improvement = False
    if log and log[-1].outcome == "pending_review":
        accepted = (
            not failed
            and best_review is not None
            and prefer_candidate(best_review, review, payload.analysis)
        )
        outcome = (
            "failed"
            if failed
            else "accepted"
            if accepted
            else "no_change"
            if best is not None
            and bundle.paragraphs == best.paragraphs
            and bundle.subtitle == best.subtitle
            else "rejected"
        )
        log = (
            *log[:-1],
            log[-1].model_copy(
                update={
                    "outcome": outcome,
                    "reason": "현재 근거와 유효 답 보존을 우선하여 수정 후보를 비교했습니다.",
                }
            ),
        )
        no_improvement = not accepted and not failed
        if not accepted and best is not None and best_review is not None:
            bundle, review = best, best_review
    control = control_for(review, count, failed=failed, no_improvement=no_improvement)
    if control.stop:
        bundle, review = safe_delivery_pair(payload, bundle, review)
    validate_contract(
        review_context(payload, bundle, review).model_copy(update={"repair_log": log})
    )
    return {
        "reviewed_bundle": bundle,
        "review": review,
        "best_bundle": bundle,
        "best_review": review,
        "review_control": control,
        "stop_reason": control.reason,
        "repair_log": log,
        "technical_issues": issues,
        "usage": usage,
    }


async def repair_draft(state: EssayState, deps: SupervisorDeps) -> EssayUpdate:
    """Consume one repair entry before generation; a failed entry cannot restart repair."""
    base, review = state.get("best_bundle"), state.get("best_review")
    count = state.get("repair_count", 0) + 1
    if base is None or review is None or count > MAX_REPAIRS:
        code = "repair_state"
        raise ContractViolation(code, "Repair requires a best pair and remaining budget")
    current = review_payload(state)
    payload = RepairPayload(
        request=current.request,
        evidence_version=current.evidence_version,
        sources=current.sources,
        facts=current.facts,
        analysis=current.analysis,
        outline=current.outline,
        writing_report=current.writing_report,
        integration_report=current.integration_report,
        fallback_provenance=current.fallback_provenance,
        candidate_bundle=base,
        repair_count=count,
        review=review,
    )
    entry = RepairLogEntry(
        attempt=count,
        base_version_id=base.version_id,
        proposed_version_id=None,
        outcome="pending_review",
        target_issue_ids=tuple(t.issue_id for t in review.repair_targets),
        reason="지정된 문제에 한정하여 수정을 시도했습니다.",
    )
    issues, usage = state.get("technical_issues", ()), state.get("usage", ())
    try:
        generated = await deps.quality_llm.generate("repair_draft", payload, RepairOutput)
        output = generated.output
        changed_body = output.paragraphs != base.paragraphs
        bundle = base.model_copy(
            update={
                "version_id": new_version(),
                "paragraphs": output.paragraphs,
                "subtitle": None if changed_body else output.subtitle,
                "subtitle_fact_ids": () if changed_body else output.subtitle_fact_ids,
            }
        )
        entry = entry.model_copy(update={"proposed_version_id": bundle.version_id})
        usage += (generated.usage,)
    except GenerationError as error:
        bundle = base
        entry = entry.model_copy(
            update={"outcome": "failed", "reason": "수정 단계 오류로 이전 검토본을 유지했습니다."}
        )
        issues += (generation_issue("repair_draft", error),)
        usage += (error.usage,)
    return {
        "repair_count": count,
        "repair_log": (*state.get("repair_log", ()), entry),
        "candidate_bundle": bundle,
        "technical_issues": issues,
        "usage": usage,
    }
