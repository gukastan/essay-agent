"""Create versioned review records from current model judgments and Python measurements."""

from .composition_rules import general_fallback, new_version, personalization_for
from .contracts import (
    ContractContext,
    DraftBundle,
    DraftParagraph,
    IssueId,
    ParagraphId,
    Quality,
    Review,
    ReviewIssue,
    SentenceCheck,
)
from .review_checks import repair_targets, requirement_checks, sentence_checks
from .review_conditions import apply_known_conditions
from .review_titles import generic_title, measure_final, title_for_body
from .stage_review_models import ReviewOutput, ReviewPayload


def review_context(payload: ReviewPayload, bundle: DraftBundle, review: Review) -> ContractContext:
    """Validate the chosen pair independently of stale composition history."""
    return ContractContext(
        evidence_version=payload.evidence_version,
        fallback_provenance=tuple(
            original
            for original in payload.fallback_provenance
            if any(original == s for p in bundle.paragraphs for s in p.sentences)
        ),
        sources=payload.sources,
        facts=payload.facts,
        analysis=payload.analysis,
        outline=payload.outline,
        bundle=bundle,
        review=review,
        request=payload.request,
    )


def normalize_review(payload: ReviewPayload, output: ReviewOutput) -> tuple[DraftBundle, Review]:
    """Bind title, checks, actionable issues and actual length to one fresh version."""
    if not any(p.sentences for p in payload.candidate_bundle.paragraphs):
        empty = payload.candidate_bundle.model_copy(
            update={
                "version_id": new_version(),
                "paragraphs": (
                    DraftParagraph(
                        paragraph_id=ParagraphId("fallback"), sentences=general_fallback()
                    ),
                ),
                "personalization": "non_personalized",
            }
        )
        payload = payload.model_copy(update={"candidate_bundle": empty})
    bundle, title = title_for_body(
        payload.candidate_bundle, apply_known_conditions(payload, output.title_review)
    )
    if bundle != payload.candidate_bundle:
        bundle = bundle.model_copy(update={"version_id": new_version()})
    bundle = bundle.model_copy(
        update={
            "personalization": personalization_for(
                bundle.paragraphs, payload.facts, payload.analysis, payload.outline
            )
        }
    )
    checks = sentence_checks(output, bundle)
    requirements = requirement_checks(output, payload, bundle)
    issues = list(output.issues)
    for check in checks:
        if check.status in ("unsupported", "conflicting") and not any(
            check.sentence_id in issue.sentence_ids and issue.status == "open" for issue in issues
        ):
            sentence = next(
                s
                for p in bundle.paragraphs
                for s in p.sentences
                if s.sentence_id == check.sentence_id
            )
            issues.append(
                ReviewIssue(
                    issue_id=IssueId(f"check:{check.sentence_id}"),
                    code="unsupported_claim"
                    if check.status == "unsupported"
                    else "conflicting_claim",
                    area="body",
                    sentence_ids=(check.sentence_id,),
                    section_ids=sentence.section_ids,
                    requirement_ids=(),
                    fact_ids=check.fact_ids,
                    gap_ids=(),
                    excerpt=sentence.text,
                    reason=check.reason,
                    action="remove",
                    verification="지원되지 않는 문장이 현재 본문에 없는지 확인합니다.",
                    fixable_without_new_info=True,
                    status="open",
                )
            )
    measured = measure_final(
        bundle, payload.request.length_policy, uncertain=title.condition == "uncertain"
    )
    if measured.status == "over" and not any(
        issue.code == "length" and issue.status == "open" for issue in issues
    ):
        issues.append(
            ReviewIssue(
                issue_id=IssueId("python:length"),
                code="length",
                area="submission",
                sentence_ids=(),
                section_ids=(),
                requirement_ids=(),
                fact_ids=(),
                gap_ids=(),
                excerpt=None,
                reason=(
                    f"실측 {measured.counted_chars}자가 상한 {measured.max_chars}자를 초과합니다."
                ),
                action="report",
                verification="유효한 답과 원문 범위를 유지하면서 분량을 검토할 수 있습니다.",
                fixable_without_new_info=False,
                status="open",
            )
        )
    targets = repair_targets(tuple(issues), payload)
    partial = any(c.status == "unassessed" for c in checks) or any(
        c.status == "unassessed" for c in requirements
    )
    return bundle, Review(
        version_id=bundle.version_id,
        evidence_version=payload.evidence_version,
        personalization=bundle.personalization,
        title_review=title,
        sentence_checks=checks,
        requirement_checks=requirements,
        issues=tuple(issues),
        length_check=measured,
        quality=output.quality,
        repair_targets=targets,
        fixable_without_new_info=bool(targets),
        suggestions=output.suggestions,
        review_status="partial" if partial else "performed",
    )


def unavailable_review(payload: ReviewPayload, *, replace_body: bool) -> tuple[DraftBundle, Review]:
    """Keep no fabricated assessment when the whole review could not be completed."""
    bundle = payload.candidate_bundle
    if replace_body:
        bundle = bundle.model_copy(
            update={
                "version_id": new_version(),
                "paragraphs": (
                    DraftParagraph(
                        paragraph_id=ParagraphId("fallback"), sentences=general_fallback()
                    ),
                ),
                "subtitle": None,
                "subtitle_fact_ids": (),
                "personalization": "non_personalized",
            }
        )
    current = payload.model_copy(update={"candidate_bundle": bundle})
    output = ReviewOutput(
        title_review=generic_title(bundle.subtitle_placement),
        sentence_checks=tuple(
            SentenceCheck(
                sentence_id=s.sentence_id,
                fact_ids=s.fact_ids,
                status="unassessed",
                reason="모델 검토를 완료하지 못했습니다.",
            )
            for p in bundle.paragraphs
            for s in p.sentences
        ),
        requirement_checks=(),
        issues=(),
        quality=Quality(specificity="limited", prompt_coverage="limited", coherence="limited"),
        suggestions=(),
    )
    titled, review = normalize_review(current, output)
    return titled, review.model_copy(
        update={
            "review_status": "unavailable",
            "repair_targets": (),
            "fixable_without_new_info": False,
        }
    )
