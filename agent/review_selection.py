"""Choose safe improvements before applying the shared bounded repair router."""

from .contract_review_validation import MAX_REPAIRS
from .contracts import Analysis, DraftBundle, Review, ReviewControl


def prefer_candidate(old: Review, new: Review, analysis: Analysis) -> bool:
    """Reject new harm or lost valid required answers before comparing bounded quality signals."""
    unsafe = {"unsupported_claim", "conflicting_claim", "submission_condition"}
    old_bad = sum(i.status == "open" and i.code in unsafe for i in old.issues)
    new_bad = sum(i.status == "open" and i.code in unsafe for i in new.issues)
    old_findings = {
        (i.code, i.sentence_ids, i.section_ids, i.fact_ids)
        for i in old.issues
        if i.status == "open" and i.code in unsafe
    }
    new_findings = {
        (i.code, i.sentence_ids, i.section_ids, i.fact_ids)
        for i in new.issues
        if i.status == "open" and i.code in unsafe
    }
    if new_bad > old_bad or not new_findings <= old_findings:
        return False
    old_checks = {r.requirement_id: r for r in old.requirement_checks}
    new_checks = {r.requirement_id: r for r in new.requirement_checks}
    source_supported = {
        c.sentence_id for c in old.sentence_checks if c.status == "source_supported"
    }
    unsafe_old_ids = {
        sid
        for issue in old.issues
        if issue.status == "open" and issue.code in unsafe
        for sid in issue.sentence_ids
    }
    source_supported.difference_update(unsafe_old_ids)
    new_supported = {c.sentence_id for c in new.sentence_checks if c.status == "source_supported"}
    for requirement in analysis.requirements:
        prior = old_checks.get(requirement.requirement_id)
        current = new_checks.get(requirement.requirement_id)
        if (
            requirement.required_by_prompt
            and prior is not None
            and prior.status in ("met", "partial")
            and source_supported.intersection(prior.body_sentence_ids)
            and (
                current is None
                or (prior.status == "met" and current.status != "met")
                or not new_supported.intersection(current.body_sentence_ids)
            )
        ):
            return False
    return quality_key(new, analysis) > quality_key(old, analysis)


def quality_key(review: Review, analysis: Analysis) -> tuple[int, int, int, int, int]:
    """Order evidence safety, excess length, direct/core coverage, and actionable expression."""
    bad = sum(
        i.status == "open"
        and i.code in ("unsupported_claim", "conflicting_claim", "submission_condition")
        for i in review.issues
    )
    excess = (
        max(0, review.length_check.counted_chars - review.length_check.max_chars)
        if review.length_check.max_chars is not None
        else 0
    )
    checks = {c.requirement_id: c.status for c in review.requirement_checks}
    direct = sum(
        checks.get(r.requirement_id) == "met" for r in analysis.requirements if r.required_by_prompt
    )
    core = sum(
        checks.get(r.requirement_id) == "met"
        for r in analysis.requirements
        if r.information_role == "logical_core"
    )
    expression = sum(
        i.status == "open" and i.code in ("style", "coherence", "subtitle") for i in review.issues
    )
    return -bad, -excess, direct, core, -expression


def control_for(
    review: Review, repair_count: int, *, failed: bool = False, no_improvement: bool = False
) -> ReviewControl:
    """Route from current review control without consulting historical technical warnings."""
    if failed:
        return ReviewControl(stop=True, reason="fallback_after_error")
    if repair_count >= MAX_REPAIRS:
        return ReviewControl(stop=True, reason="repair_limit")
    if no_improvement:
        return ReviewControl(stop=True, reason="no_improvement")
    if review.repair_targets:
        return ReviewControl(stop=False, reason=None)
    missing = any(i.code == "missing_information" and i.status == "open" for i in review.issues)
    return ReviewControl(stop=True, reason="missing_info_only" if missing else "no_fixable_issue")


def matching_pair(bundle: DraftBundle | None, review: Review | None) -> bool:
    """Test exact draft and evidence identity without promoting a stale review."""
    return (
        bundle is not None
        and review is not None
        and bundle.version_id == review.version_id
        and bundle.evidence_version == review.evidence_version
    )
