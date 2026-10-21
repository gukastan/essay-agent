"""Remove known unsupported content from a delivery copy without a third generation."""

from .composition_rules import general_fallback, new_version, personalization_for
from .contracts import DraftBundle, DraftParagraph, ParagraphId, Review, SectionId, SentenceCheck
from .review_conditions import apply_known_conditions
from .review_titles import generic_title, measure_final, title_for_body
from .stage_review_models import ReviewPayload


def safe_delivery_pair(
    payload: ReviewPayload, bundle: DraftBundle, review: Review
) -> tuple[DraftBundle, Review]:
    """Rebind all derived judgments after final safety removal; never restore unsafe baseline."""
    blocked = {
        c.sentence_id for c in review.sentence_checks if c.status in ("unsupported", "conflicting")
    }
    sections: set[SectionId] = set()
    for issue in review.issues:
        if (
            issue.status == "open"
            and issue.code in ("unsupported_claim", "conflicting_claim")
            and issue.area != "subtitle"
        ):
            blocked.update(issue.sentence_ids)
            sections.update(issue.section_ids)
            if not issue.sentence_ids:
                blocked.update(
                    s.sentence_id
                    for p in bundle.paragraphs
                    for s in p.sentences
                    if not issue.section_ids or set(issue.section_ids).intersection(s.section_ids)
                )
    blocked.update(
        s.sentence_id
        for p in bundle.paragraphs
        for s in p.sentences
        if s.claim_kind == "connective" and sections.intersection(s.section_ids)
    )
    if not blocked:
        return bundle, review
    paragraphs = tuple(
        p.model_copy(
            update={"sentences": tuple(s for s in p.sentences if s.sentence_id not in blocked)}
        )
        for p in bundle.paragraphs
    )
    paragraphs = tuple(p for p in paragraphs if p.sentences)
    if not paragraphs:
        paragraphs = (
            DraftParagraph(paragraph_id=ParagraphId("fallback"), sentences=general_fallback()),
        )
    changed = bundle.model_copy(
        update={
            "version_id": new_version(),
            "paragraphs": paragraphs,
            "personalization": personalization_for(
                paragraphs, payload.facts, payload.analysis, payload.outline
            ),
        }
    )
    prior_title = (
        review.title_review
        if review.title_review.condition == "fixed"
        else generic_title(bundle.subtitle_placement)
    )
    changed, title = title_for_body(changed, apply_known_conditions(payload, prior_title))
    ids = {s.sentence_id for p in changed.paragraphs for s in p.sentences}
    checks = {c.sentence_id: c for c in review.sentence_checks}
    new_checks = tuple(
        checks.get(s.sentence_id)
        or SentenceCheck(
            sentence_id=s.sentence_id,
            fact_ids=s.fact_ids,
            status="unassessed",
            reason="최종 안전 처리 후 추가 의미 검토는 수행하지 않았습니다.",
        )
        for p in changed.paragraphs
        for s in p.sentences
    )
    requirements = tuple(
        c.model_copy(
            update={
                "body_sentence_ids": tuple(sid for sid in c.body_sentence_ids if sid in ids),
                "fact_ids": (),
                "status": "unassessed",
                "reason": "최종 안전 처리 후 요구 반영을 다시 확인해야 합니다.",
            }
        )
        for c in review.requirement_checks
    )
    issues = tuple(
        i.model_copy(
            update={
                "sentence_ids": tuple(sid for sid in i.sentence_ids if sid in ids),
                "excerpt": None,
                "status": "resolved"
                if i.sentence_ids and set(i.sentence_ids) <= blocked
                else i.status,
            }
        )
        for i in review.issues
    )
    return changed, review.model_copy(
        update={
            "version_id": changed.version_id,
            "personalization": changed.personalization,
            "title_review": title,
            "sentence_checks": new_checks,
            "requirement_checks": requirements,
            "issues": issues,
            "length_check": measure_final(changed, payload.request.length_policy),
            "repair_targets": (),
            "fixable_without_new_info": False,
            "suggestions": (),
            "review_status": "partial",
        }
    )
