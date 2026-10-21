"""Validate semantic guidance against current origins and merge duplicate causes."""

from .contracts import Analysis, DraftBundle, Outline, Review, Suggestion
from .delivery_structure import locations_for


def current_guidance(
    bundle: DraftBundle, review: Review, analysis: Analysis, outline: Outline
) -> tuple[Suggestion, ...]:
    """Keep useful model wording only when every declared origin and target is current."""
    ids = {s.sentence_id for p in bundle.paragraphs for s in p.sentences}
    issues = {i.issue_id: i for i in review.issues if i.status == "open"}
    gaps = {
        g.gap_id: g for g in analysis.gaps if g.question_status not in ("resolved", "not_needed")
    }
    unmet = {
        r.requirement_id
        for r in review.requirement_checks
        if r.status not in ("met", "not_applicable")
    }
    requirements = {r.requirement_id for r in analysis.requirements}
    sections = {s.section_id for s in outline.sections}
    rows: list[Suggestion] = []
    for row in review.suggestions:
        if (
            not (row.issue_ids or row.gap_ids or row.requirement_ids)
            or not set(row.sentence_ids) <= ids
        ):
            continue
        if not set(row.issue_ids) <= set(issues) or not set(row.gap_ids) <= set(gaps):
            continue
        if not row.issue_ids and not row.gap_ids and not set(row.requirement_ids) <= unmet:
            continue
        if not set(row.requirement_ids) <= requirements or (
            row.section_id is not None and row.section_id not in sections
        ):
            continue
        gap = next(
            (gaps[gid] for gid in row.gap_ids if gaps[gid].question_key == row.question_key), None
        )
        question = (
            row.example_question
            if gap is not None
            and gap.question_status not in ("unavailable", "resolved", "not_needed")
            else None
        )
        rows.append(
            row.model_copy(
                update={
                    "question_key": gap.question_key if gap else None,
                    "example_question": question,
                    "next_action": "기억나는 정보가 생기면 원문에 추가할 수 있습니다."
                    if gap is not None and gap.question_status == "unavailable"
                    else row.next_action,
                    "question_status": gap.question_status if gap else "not_needed",
                    "locations": locations_for(bundle, row.sentence_ids),
                }
            )
        )
    return tuple(rows)


def merge_causes(
    rows: tuple[Suggestion, ...], bundle: DraftBundle, review: Review
) -> tuple[Suggestion, ...]:
    """Combine shared gap IDs or identical issue code/targets while preserving all origins."""
    groups: list[Suggestion] = []
    for row in rows:
        found = next(
            (index for index, existing in enumerate(groups) if same_cause(existing, row, review)),
            None,
        )
        if found is None:
            groups.append(row)
            continue
        existing = groups[found]
        ids = tuple(dict.fromkeys((*existing.sentence_ids, *row.sentence_ids)))
        rank = {"required_edit": 0, "required_info": 1, "optional": 2}
        question = existing if existing.question_key else row
        groups[found] = existing.model_copy(
            update={
                "sentence_ids": ids,
                "issue_ids": tuple(dict.fromkeys((*existing.issue_ids, *row.issue_ids))),
                "gap_ids": tuple(dict.fromkeys((*existing.gap_ids, *row.gap_ids))),
                "requirement_ids": tuple(
                    dict.fromkeys((*existing.requirement_ids, *row.requirement_ids))
                ),
                "locations": locations_for(bundle, ids),
                "category": min((existing.category, row.category), key=rank.__getitem__),
                "question_key": question.question_key,
                "question_status": question.question_status,
                "example_question": question.example_question,
            }
        )
    return tuple(groups)


def same_cause(first: Suggestion, second: Suggestion, review: Review) -> bool:
    """Avoid merging unrelated gaps merely because their human labels look alike."""
    if set(first.gap_ids).intersection(second.gap_ids):
        return True
    issues = {i.issue_id: i for i in review.issues}
    first_keys = {
        (
            issues[iid].code,
            issues[iid].sentence_ids,
            issues[iid].section_ids,
            frozenset(issues[iid].requirement_ids),
        )
        for iid in first.issue_ids
        if iid in issues
    }
    second_keys = {
        (
            issues[iid].code,
            issues[iid].sentence_ids,
            issues[iid].section_ids,
            frozenset(issues[iid].requirement_ids),
        )
        for iid in second.issue_ids
        if iid in issues
    }
    return bool(first_keys.intersection(second_keys))
