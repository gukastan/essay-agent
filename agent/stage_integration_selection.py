"""Reject unsafe edits and restore only still-valid baseline content."""

from typing import Final

from .composition_rules import general_fallback, length_snapshot, new_version, personalization_for
from .contract_composition_validation import bundle_sentences
from .contracts import DraftBundle, DraftParagraph, IntegrationIssue, IntegrationReport, ParagraphId
from .stage_integration_contract import proposed_pair
from .stage_integration_models import IntegrationOutput, IntegrationPayload
from .stage_integration_records import (
    restoration_edits,
    structural_reverse,
    unassessed_requirements,
)

UNSAFE_CODES: Final = frozenset(
    (
        "unsupported_claim",
        "conflict",
        "unsupported_causality",
        "unsupported_metric",
        "attribution",
        "sole_answer_lost",
        "requirement_loss",
        "contract_mismatch",
    )
)


def reject_edit(output: IntegrationOutput, payload: IntegrationPayload) -> bool:
    """Act on reported semantic damage without starting a quality retry loop."""
    if any(issue.code in UNSAFE_CODES and issue.status == "open" for issue in output.issues):
        return True
    required = {r.requirement_id for r in payload.analysis.requirements if r.required_by_prompt}
    if any(
        check.requirement_id in required
        and check.before_state == "expressed"
        and check.after_state in ("partial", "not_expressed")
        for check in output.requirement_checks
    ):
        return True
    before = bundle_sentences(payload.baseline_bundle)
    after = tuple(s for p in output.paragraphs for s in p.sentences)
    for requirement in required:
        sections = {
            s.section_id for s in payload.outline.sections if requirement in s.requirement_ids
        }
        if any(s.fact_ids and sections.intersection(s.section_ids) for s in before) and not any(
            s.fact_ids and sections.intersection(s.section_ids) for s in after
        ):
            return True
    return not after


def restore_baseline(
    payload: IntegrationPayload, issues: tuple[IntegrationIssue, ...]
) -> tuple[DraftBundle, IntegrationReport]:
    """Remove known baseline errors, preserve the historical baseline, and invalidate meanings."""
    baseline = payload.baseline_bundle
    unsafe = tuple(
        issue
        for issue in issues
        if issue.scope == "baseline" and issue.status == "open" and issue.code in UNSAFE_CODES
    )
    blocked = {sid for issue in unsafe for sid in issue.sentence_ids}
    sections = {sid for issue in unsafe for sid in issue.section_ids}
    for issue in unsafe:
        if not issue.sentence_ids:
            blocked.update(
                sentence.sentence_id
                for sentence in bundle_sentences(baseline)
                if not issue.section_ids
                or set(issue.section_ids).intersection(sentence.section_ids)
            )
    bad_sentences = tuple(s for s in bundle_sentences(baseline) if s.sentence_id in blocked)
    blocked.update(
        s.sentence_id
        for s in bundle_sentences(baseline)
        if any(
            (s.text, s.fact_ids, s.claim_kind) == (bad.text, bad.fact_ids, bad.claim_kind)
            for bad in bad_sentences
        )
    )
    blocked.update(
        s.sentence_id
        for s in bundle_sentences(baseline)
        if s.claim_kind == "connective" and sections.intersection(s.section_ids)
    )
    paragraphs = tuple(
        p.model_copy(
            update={"sentences": tuple(s for s in p.sentences if s.sentence_id not in blocked)}
        )
        for p in baseline.paragraphs
    )
    paragraphs = tuple(p for p in paragraphs if p.sentences)
    fallback = not paragraphs or all(not s.section_ids for p in paragraphs for s in p.sentences)
    if fallback:
        paragraphs = (
            DraftParagraph(paragraph_id=ParagraphId("fallback"), sentences=general_fallback()),
        )
    changed = paragraphs != baseline.paragraphs
    bundle = (
        baseline
        if not changed
        else baseline.model_copy(
            update={
                "version_id": new_version(),
                "paragraphs": paragraphs,
                "personalization": personalization_for(
                    paragraphs, payload.facts, payload.analysis, payload.outline
                ),
            }
        )
    )
    kept_ids = {s.sentence_id for s in bundle_sentences(bundle)}
    normalized_issues = tuple(
        issue.model_copy(
            update={
                "scope": "baseline" if issue.scope == "baseline" else "rejected_candidate",
                "status": "resolved"
                if issue.sentence_ids and not set(issue.sentence_ids) & kept_ids
                else issue.status,
                "handling": "수정안을 거절하고 기준본에서 알려진 부당 주장만 제외했습니다.",
            }
        )
        for issue in issues
    )
    report = IntegrationReport(
        source_draft_id=payload.writing_report.draft_id,
        evidence_version=payload.evidence_version,
        baseline_bundle=baseline,
        candidate_version_id=bundle.version_id,
        selection="general_fallback" if fallback else "edited" if changed else "baseline",
        selection_reason="편집 오류 또는 보고된 의미 훼손으로 기준본의 유효 내용을 보존했습니다.",
        edits=restoration_edits(baseline, bundle),
        reverse_outline=structural_reverse(baseline, "baseline")
        + structural_reverse(bundle, "candidate"),
        requirement_checks=unassessed_requirements(
            baseline, bundle, payload.analysis, payload.outline
        ),
        length_before=length_snapshot(baseline, payload.request.length_policy),
        length_after=length_snapshot(bundle, payload.request.length_policy),
        issues=normalized_issues,
    )
    return bundle, report


def select_integration(
    payload: IntegrationPayload, output: IntegrationOutput
) -> tuple[DraftBundle, IntegrationReport]:
    """Select one proposal or one conservative baseline path without extra generation."""
    if reject_edit(output, payload):
        return restore_baseline(payload, output.issues)
    return proposed_pair(payload, output)
