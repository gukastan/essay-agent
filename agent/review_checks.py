"""Normalize missing judgments conservatively and derive actionable targets."""

from .contracts import DraftBundle, RepairTarget, RequirementCheck, ReviewIssue, SentenceCheck
from .stage_evidence import eligible_links
from .stage_review_models import ReviewOutput, ReviewPayload


def sentence_checks(output: ReviewOutput, bundle: DraftBundle) -> tuple[SentenceCheck, ...]:
    """Missing current sentence judgments are unassessed, never implicitly approved."""
    checks = {check.sentence_id: check for check in output.sentence_checks}
    return tuple(
        checks.get(sentence.sentence_id)
        or SentenceCheck(
            sentence_id=sentence.sentence_id,
            fact_ids=sentence.fact_ids,
            status="unassessed",
            reason="이 문장의 의미 대조가 완료되지 않았습니다.",
        )
        for p in bundle.paragraphs
        for sentence in p.sentences
    )


def requirement_checks(
    output: ReviewOutput, payload: ReviewPayload, bundle: DraftBundle
) -> tuple[RequirementCheck, ...]:
    """Keep raw unparsed questions and absent comparisons explicitly unassessed."""
    supplied = {row.requirement_id: row for row in output.requirement_checks}
    checks = {row.sentence_id: row for row in sentence_checks(output, bundle)}
    rows: list[RequirementCheck] = []
    for requirement in payload.analysis.requirements:
        row = supplied.get(requirement.requirement_id) or RequirementCheck(
            requirement_id=requirement.requirement_id,
            body_sentence_ids=(),
            fact_ids=(),
            status="unassessed",
            missing_detail=requirement.description,
            reason="현재 본문 요구 검토가 완료되지 않았습니다.",
        )
        if requirement.resolution == "unparsed" or (
            row.status == "met"
            and (
                not row.body_sentence_ids
                or any(
                    checks[sid].status not in ("source_supported", "general_valid")
                    for sid in row.body_sentence_ids
                )
            )
        ):
            row = row.model_copy(update={"status": "unassessed"})
        if requirement.required_by_prompt and row.status == "not_applicable":
            row = row.model_copy(update={"status": "unassessed"})
        personal = any(
            s.write_mode != "general" and requirement.requirement_id in s.requirement_ids
            for s in payload.outline.sections
        )
        if (
            personal
            and row.status == "met"
            and not any(checks[sid].status == "source_supported" for sid in row.body_sentence_ids)
        ):
            row = row.model_copy(update={"status": "unmet"})
        rows.append(row)
    return tuple(rows)


def repair_targets(
    issues: tuple[ReviewIssue, ...], payload: ReviewPayload
) -> tuple[RepairTarget, ...]:
    """Only explicit current actions with existing permissible facts trigger repairs."""
    eligible = {
        fid for link in eligible_links(payload.analysis, payload.facts) for fid in link.fact_ids
    }
    plans = {s.section_id: s for s in payload.outline.sections}
    targets: list[RepairTarget] = []
    for issue in issues:
        if (
            issue.status != "open"
            or not issue.fixable_without_new_info
            or issue.code == "missing_information"
            or issue.action in ("suggest", "report")
        ):
            continue
        allowed = set(eligible)
        for sid in issue.section_ids:
            allowed.intersection_update(plans[sid].fact_ids)
        if issue.action == "restore_allowed" and not allowed:
            continue
        targets.append(
            RepairTarget(
                issue_id=issue.issue_id,
                area=issue.area,
                sentence_ids=issue.sentence_ids,
                section_ids=issue.section_ids,
                allowed_fact_ids=tuple(fid for fid in eligible if fid in allowed),
                operation=issue.action,
                preserve_requirement_ids=issue.requirement_ids,
                acceptance_check=issue.verification,
            )
        )
    return tuple(targets)
