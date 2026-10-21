"""Offline literal oracle for current payloads, not a semantic model quality certificate."""

from .contracts import (
    IssueId,
    Quality,
    RequirementCheck,
    ReviewIssue,
    SentenceCheck,
    TitleCandidate,
    TitleClaim,
    TitleReview,
)
from .review_titles import generic_title
from .stage_review_models import ReviewOutput, ReviewPayload


def review_literals(payload: ReviewPayload) -> ReviewOutput:
    """Approve literal quotes and leave other semantic transformations unassessed."""
    bundle = payload.candidate_bundle
    sentences = tuple(s for p in bundle.paragraphs for s in p.sentences)
    facts = {f.fact_id: f for f in payload.facts}
    checks = tuple(
        SentenceCheck(
            sentence_id=s.sentence_id,
            fact_ids=s.fact_ids,
            status="source_supported"
            if s.fact_ids and all(s.text == facts[fid].quote for fid in s.fact_ids)
            else "general_valid"
            if s.claim_kind in ("general_statement", "connective") and not s.fact_ids
            else "unassessed",
            reason="오프라인 원문 문자열 일치 검사이며 의미 품질 인증이 아닙니다.",
        )
        for s in sentences
    )
    requirements: list[RequirementCheck] = []
    issues: list[ReviewIssue] = []
    for requirement in payload.analysis.requirements:
        sections = tuple(
            s for s in payload.outline.sections if requirement.requirement_id in s.requirement_ids
        )
        ids = tuple(
            s.sentence_id
            for s in sentences
            if any(section.section_id in s.section_ids for section in sections) and s.fact_ids
        )
        fids = tuple(
            dict.fromkeys(fid for s in sentences if s.sentence_id in ids for fid in s.fact_ids)
        )
        status = "unassessed" if requirement.resolution == "unparsed" else "met" if ids else "unmet"
        requirements.append(
            RequirementCheck(
                requirement_id=requirement.requirement_id,
                body_sentence_ids=ids,
                fact_ids=fids,
                status=status,
                missing_detail=None if ids else requirement.description,
                reason="현재 원문 문장과 계획상 요구 연결을 대조했습니다.",
            )
        )
        if not ids and requirement.resolution != "unparsed":
            allowed = tuple(dict.fromkeys(fid for section in sections for fid in section.fact_ids))
            issues.append(
                ReviewIssue(
                    issue_id=IssueId(f"requirement:{requirement.requirement_id}"),
                    code="prompt_coverage" if allowed else "missing_information",
                    area="body",
                    sentence_ids=(),
                    section_ids=tuple(s.section_id for s in sections),
                    requirement_ids=(requirement.requirement_id,),
                    fact_ids=allowed,
                    gap_ids=tuple(
                        g.gap_id
                        for g in payload.analysis.gaps
                        if requirement.requirement_id in g.requirement_ids
                    ),
                    excerpt=None,
                    reason=requirement.description,
                    action="restore_allowed" if allowed else "suggest",
                    verification="이미 제공한 원문 범위에서 해당 부분의 반영을 확인합니다."
                    if allowed
                    else "기억나는 정보가 있을 때 원문에 추가할 수 있습니다.",
                    fixable_without_new_info=bool(allowed),
                    status="open",
                )
            )
    title = generic_title(bundle.subtitle_placement)
    grounded = next((s for s in sentences if s.fact_ids), None)
    if grounded is not None:
        candidate = TitleCandidate(
            id="literal",
            text=grounded.text,
            kind="generated",
            claims=(
                TitleClaim(
                    meaning=grounded.text,
                    body_sentence_ids=(grounded.sentence_id,),
                    fact_ids=grounded.fact_ids,
                ),
            ),
            checks=(),
            decision="selected",
            reason="현재 본문의 원문 진술을 그대로 예고합니다.",
        )
        title = TitleReview(
            condition="allowed",
            condition_refs=(),
            placement="answer",
            reason="현재 본문 근거 범위의 제목입니다.",
            focus_summary=grounded.text,
            candidates=(candidate,),
            selected_candidate_id=candidate.id,
        )
    question = payload.request.question or ""
    if "제목 금지" in question or "소제목을 쓰지" in question:
        title = title.model_copy(
            update={
                "condition": "forbidden",
                "placement": "display_only",
                "condition_refs": (question,),
            }
        )
    return ReviewOutput(
        title_review=title,
        sentence_checks=checks,
        requirement_checks=tuple(requirements),
        issues=tuple(issues),
        quality=Quality(
            specificity="limited" if payload.analysis.gaps else "adequate",
            prompt_coverage="limited" if issues else "adequate",
            coherence="adequate",
        ),
        suggestions=(),
    )
