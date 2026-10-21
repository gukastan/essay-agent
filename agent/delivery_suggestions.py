"""Convert only current issues and unresolved information gaps into optional next actions."""

from .contracts import Analysis, DraftBundle, Outline, Review, Suggestion
from .delivery_structure import locations_for
from .delivery_suggestion_merge import current_guidance, merge_causes


def suggestions_for(
    bundle: DraftBundle, review: Review, analysis: Analysis, outline: Outline
) -> tuple[Suggestion, ...]:
    """Exclude stale/resolved questions and retain unavailable gaps without asking again."""
    rows: list[Suggestion] = list(current_guidance(bundle, review, analysis, outline))
    required = {
        r.requirement_id
        for r in analysis.requirements
        if r.required_by_prompt or r.information_role == "logical_core"
    }
    met = {r.requirement_id for r in review.requirement_checks if r.status == "met"}
    for issue in review.issues:
        if issue.status != "open":
            continue
        section = issue.section_ids[0] if issue.section_ids else None
        area = (
            "body"
            if issue.area == "structure" and section is not None
            else "whole_answer"
            if issue.area == "structure"
            else issue.area
        )
        rows.append(
            Suggestion.model_validate(
                {
                    "section_id": section,
                    "area": area,
                    "sentence_ids": issue.sentence_ids,
                    "requirement_ids": issue.requirement_ids,
                    "issue_ids": (issue.issue_id,),
                    "gap_ids": issue.gap_ids,
                    "question_key": None,
                    "category": "required_info"
                    if issue.code == "missing_information"
                    else "required_edit"
                    if issue.fixable_without_new_info
                    or (
                        issue.code == "prompt_coverage"
                        and bool(required.intersection(issue.requirement_ids))
                    )
                    or issue.code
                    in ("length", "submission_condition", "unsupported_claim", "conflicting_claim")
                    else "optional",
                    "missing_detail": issue.reason,
                    "why_it_helps": issue.verification,
                    "next_action": issue.verification,
                    "example_question": None,
                    "question_status": "not_needed",
                    "priority": 0,
                    "locations": locations_for(bundle, issue.sentence_ids),
                }
            )
        )
    for gap in analysis.gaps:
        if gap.question_status in ("resolved", "not_needed") or set(gap.requirement_ids) <= met:
            continue
        sections = tuple(s for s in outline.sections if gap.gap_id in s.gap_ids)
        ids = tuple(
            s.sentence_id
            for p in bundle.paragraphs
            for s in p.sentences
            if any(section.section_id in s.section_ids for section in sections)
        )
        unavailable = gap.question_status == "unavailable"
        rows.append(
            Suggestion(
                section_id=sections[0].section_id if sections else None,
                area="body" if sections else "whole_answer",
                sentence_ids=ids,
                requirement_ids=gap.requirement_ids,
                issue_ids=(),
                gap_ids=(gap.gap_id,),
                question_key=gap.question_key,
                category="required_info"
                if required.intersection(gap.requirement_ids)
                else "optional",
                missing_detail=gap.missing_detail,
                why_it_helps=gap.why_it_matters,
                next_action="기억나는 정보가 생기면 원문에 추가할 수 있습니다."
                if unavailable
                else gap.question or gap.missing_detail,
                example_question=None if unavailable else gap.question,
                question_status=gap.question_status,
                priority=0,
                locations=locations_for(bundle, ids),
            )
        )
    covered = {rid for row in rows for rid in row.requirement_ids}
    for check in review.requirement_checks:
        if check.status in ("met", "not_applicable") or check.requirement_id in covered:
            continue
        section = next(
            (s for s in outline.sections if check.requirement_id in s.requirement_ids), None
        )
        rows.append(
            Suggestion(
                section_id=section.section_id if section else None,
                area="body" if section else "whole_answer",
                sentence_ids=check.body_sentence_ids,
                requirement_ids=(check.requirement_id,),
                issue_ids=(),
                gap_ids=(),
                question_key=None,
                category="required_info" if check.requirement_id in required else "optional",
                missing_detail=check.missing_detail or check.reason,
                why_it_helps=check.reason,
                next_action="현재 원문과 이 요구의 실제 반영을 확인할 수 있습니다.",
                example_question=None,
                question_status="not_needed",
                priority=0,
                locations=locations_for(bundle, check.body_sentence_ids),
            )
        )
    rows = list(merge_causes(tuple(rows), bundle, review))
    order = {"required_edit": 0, "required_info": 1, "optional": 2}
    positions = {
        s.sentence_id: (pindex, sindex)
        for pindex, p in enumerate(bundle.paragraphs)
        for sindex, s in enumerate(p.sentences)
    }
    rows.sort(
        key=lambda row: (
            order[row.category],
            min((positions[sid] for sid in row.sentence_ids), default=(len(bundle.paragraphs), 0)),
        )
    )
    return tuple(row.model_copy(update={"priority": index}) for index, row in enumerate(rows, 1))
