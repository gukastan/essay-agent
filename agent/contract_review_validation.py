"""Public contract_review_validation boundary contracts."""

from typing import Final

from .contract_base import require
from .contract_composition_validation import bundle_sentences
from .contract_context import ContractContext
from .contract_references import references, unique

MAX_REPAIRS: Final = 2


def validate_review(ctx: ContractContext) -> None:
    """Enforce validate review boundary semantics."""
    review = ctx.review
    if review is None:
        return
    require(ctx.bundle is not None, "missing_context", "Review requires current bundle")
    if ctx.bundle is None:
        return
    bundle = ctx.bundle
    sentences = {s.sentence_id: s for s in bundle_sentences(bundle)}
    facts = {f.fact_id for f in ctx.facts}
    requirements = {r.requirement_id: r for r in ctx.analysis.requirements} if ctx.analysis else {}
    sections = {s.section_id: s for s in ctx.outline.sections} if ctx.outline else {}
    require(
        review.version_id == bundle.version_id and review.evidence_version == ctx.evidence_version,
        "review_version",
        "Review must describe selected version",
    )
    require(
        unique((c.sentence_id for c in review.sentence_checks), "sentence checks")
        == set(sentences),
        "sentence_checks",
        "Every current sentence needs exactly one check",
    )
    for check in review.sentence_checks:
        references(check.fact_ids, sentences[check.sentence_id].fact_ids, "sentence check facts")
        require(
            check.status != "source_supported" or bool(check.fact_ids),
            "positive_evidence",
            "Supported checks require affirmative source links",
        )
        require(
            check.status != "general_valid"
            or sentences[check.sentence_id].claim_kind in ("general_statement", "connective"),
            "general_check",
            "General check cannot approve a personal claim",
        )
    for check in review.requirement_checks:
        references((check.requirement_id,), requirements, "review requirement")
        references(check.body_sentence_ids, sentences, "requirement body")
        references(check.fact_ids, facts, "requirement facts")
        require(
            requirements[check.requirement_id].resolution != "unparsed"
            or check.status == "unassessed",
            "unparsed_requirement",
            "Unparsed requirements remain unassessed",
        )
        require(
            not requirements[check.requirement_id].required_by_prompt
            or check.status != "not_applicable",
            "required_applicability",
            "Required requirements remain applicable",
        )
    _validate_title(ctx)
    issues = {i.issue_id: i for i in review.issues}
    _ = unique((i.issue_id for i in review.issues), "review issues")
    for issue in review.issues:
        references(issue.sentence_ids, sentences, "issue sentences")
        references(issue.fact_ids, facts, "issue facts")
        references(issue.section_ids, sections, "issue sections")
        references(issue.requirement_ids, requirements, "issue requirements")
        references(
            issue.gap_ids,
            (gap.gap_id for gap in ctx.analysis.gaps) if ctx.analysis else (),
            "issue gaps",
        )
    for target in review.repair_targets:
        references((target.issue_id,), issues, "repair issue")
        require(
            issues[target.issue_id].fixable_without_new_info
            and issues[target.issue_id].status == "open",
            "repair_actionable",
            "Only actionable current issues can be repaired",
        )
        references(target.sentence_ids, sentences, "repair sentences")
        references(target.allowed_fact_ids, facts, "repair facts")
        references(target.section_ids, sections, "repair sections")
        for sid in target.section_ids:
            require(
                sections[sid].write_mode != "omit" or not target.allowed_fact_ids,
                "repair_omit",
                "Repair cannot introduce personal claims into omitted sections",
            )
            references(target.allowed_fact_ids, sections[sid].fact_ids, "repair allowed evidence")
    require(
        review.length_check.version_id == bundle.version_id,
        "length_version",
        "Length check describes current version",
    )
    require(
        len(ctx.repair_log) <= MAX_REPAIRS
        and tuple(entry.attempt for entry in ctx.repair_log)
        == tuple(range(1, len(ctx.repair_log) + 1)),
        "repair_budget",
        "Repair attempts are ordered and capped at two",
    )


def _validate_title(ctx: ContractContext) -> None:
    if ctx.review is None or ctx.bundle is None:
        return
    review = ctx.review
    bundle = ctx.bundle
    sentences = {s.sentence_id: s for s in bundle_sentences(bundle)}
    facts = {f.fact_id for f in ctx.facts}
    title = review.title_review
    require(
        title.placement == bundle.subtitle_placement,
        "title_placement",
        "Title placement must match bundle",
    )
    _ = unique((c.id for c in title.candidates), "title candidates")
    selected = [c for c in title.candidates if c.id == title.selected_candidate_id]
    if title.selected_candidate_id is not None:
        require(
            len(selected) == 1
            and selected[0].text == bundle.subtitle
            and selected[0].decision == "selected",
            "selected_title",
            "Selected title must be current title",
        )
    for candidate in selected:
        require(
            set(bundle.subtitle_fact_ids)
            == {fid for claim in candidate.claims for fid in claim.fact_ids},
            "title_evidence",
            "Selected title evidence must match its reviewed claims",
        )
        for claim in candidate.claims:
            references(claim.body_sentence_ids, sentences, "title current body")
            references(claim.fact_ids, facts, "title facts")
            body_facts = {fid for sid in claim.body_sentence_ids for fid in sentences[sid].fact_ids}
            references(claim.fact_ids, body_facts, "title claim must follow body evidence")
