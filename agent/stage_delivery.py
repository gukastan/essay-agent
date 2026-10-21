"""Assemble a single immutable result with zero model calls."""

from __future__ import annotations

from typing import TYPE_CHECKING

from .contracts import (
    EssayResult,
    QualityReport,
    ReviewControl,
    SourceSummary,
    count_characters,
    counted_text,
    render_body,
    render_copy_text,
    validate_contract,
)
from .delivery_structure import structure_for
from .delivery_suggestions import suggestions_for
from .review_normalization import review_context, unavailable_review
from .review_selection import matching_pair
from .review_titles import measure_final
from .stage_review_nodes import review_payload

if TYPE_CHECKING:
    from .deps import SupervisorDeps
    from .graph_state import EssayState, EssayUpdate


async def deliver_result(state: EssayState, deps: SupervisorDeps) -> EssayUpdate:
    """Lock a matching reviewed pair and derive only locations, strings and measurements."""
    del deps
    payload = review_payload(state)
    bundle, review = state.get("best_bundle"), state.get("best_review")
    fallback = False
    if not matching_pair(bundle, review):
        bundle, review = state.get("reviewed_bundle"), state.get("review")
    if not matching_pair(bundle, review) or bundle is None or review is None:
        bundle, review = unavailable_review(payload, replace_body=True)
        fallback = True
    measured = measure_final(
        bundle,
        payload.request.length_policy,
        uncertain=review.length_check.condition_status == "unassessed",
    )
    if measured != review.length_check:
        measured = measured.model_copy(
            update={
                "condition_status": "unassessed",
                "notes": (*measured.notes, "이전 분량 기록과 현재 실측이 달라 다시 계산했습니다."),
            }
        )
        review = review.model_copy(update={"length_check": measured, "review_status": "partial"})
    suggestions = suggestions_for(bundle, review, payload.analysis, payload.outline)
    required = {
        r.requirement_id
        for r in payload.analysis.requirements
        if r.required_by_prompt or r.information_role == "logical_core"
    }
    checks = {c.requirement_id: c for c in review.requirement_checks}
    incomplete = (
        review.review_status != "performed"
        or measured.condition_status == "unassessed"
        or any(rid not in checks or checks[rid].status == "unassessed" for rid in required)
        or any(c.status == "unassessed" for c in review.sentence_checks)
    )
    required_count = sum(row.category != "optional" for row in suggestions)
    remaining_required = any(
        rid not in checks or checks[rid].status not in ("met", "not_applicable") for rid in required
    )
    display = (
        "review_incomplete"
        if incomplete
        else "needs_attention"
        if required_count or remaining_required or measured.status == "over"
        else "reviewed_draft"
    )
    guidance = (
        ("개인 경험이 반영되지 않은 일반 초안입니다.",)
        if bundle.personalization == "non_personalized"
        else ()
    )
    if incomplete:
        guidance += ("일부 검토가 완료되지 않았으며 제공된 정보 범위에서 확인이 필요합니다.",)
    if not required_count:
        guidance += ("현재 기록된 필수 보완 사항은 없습니다.",)
    quality = QualityReport.model_validate(
        {
            **review.quality.model_dump(),
            "review_status": review.review_status,
            "display_status": display,
            "length_check": measured,
            "subtitle_reason": review.title_review.reason,
            "required_item_count": required_count,
            "key_guidance": guidance,
            "unverified_conditions": measured.notes,
            "technical_limits": tuple(issue.message for issue in state.get("technical_issues", ())),
        }
    )
    used = {fid for p in bundle.paragraphs for s in p.sentences for fid in s.fact_ids}
    summaries = tuple(
        SourceSummary(
            source_kind=kind,
            provided_source_count=sum(s.source_kind == kind for s in payload.sources),
            used_fact_count=sum(f.source_kind == kind and f.fact_id in used for f in payload.facts),
        )
        for kind in ("applicant", "company", "job_posting")
    )
    stop = (
        "fallback_after_error" if fallback else state.get("stop_reason") or "fallback_after_error"
    )
    result = EssayResult(
        document_id=payload.request.document_id,
        request_id=payload.request.request_id,
        version_id=bundle.version_id,
        evidence_version=payload.evidence_version,
        subtitle=bundle.subtitle or "",
        subtitle_placement=bundle.subtitle_placement,
        body=render_body(bundle),
        copy_text=render_copy_text(bundle),
        character_count=count_characters(
            counted_text(bundle, payload.request.length_policy), payload.request.length_policy
        ),
        length_policy=payload.request.length_policy,
        personalization=bundle.personalization,
        structure=structure_for(bundle, review, payload.outline),
        suggestions=suggestions,
        quality_report=quality,
        source_summary=summaries,
        generation_status="completed_with_fallback"
        if fallback or review.review_status == "unavailable" or state.get("technical_issues")
        else "completed",
        stop_reason=stop,
    )
    log = tuple(
        entry.model_copy(
            update={
                "outcome": "failed",
                "reason": "완료되지 않은 수정 검토를 전달 전 종료했습니다.",
            }
        )
        if entry.outcome == "pending_review"
        else entry
        for entry in state.get("repair_log", ())
    )
    validate_contract(
        review_context(payload, bundle, review).model_copy(
            update={"result": result, "repair_log": log}
        )
    )
    return {
        "result": result,
        "best_bundle": bundle,
        "best_review": review,
        "repair_log": log,
        "reviewed_bundle": bundle,
        "review": review,
        "stop_reason": stop,
        "review_control": ReviewControl(stop=True, reason=stop),
    }
