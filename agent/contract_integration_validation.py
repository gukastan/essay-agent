"""Integration candidate lineage and complete edit mappings."""

from .contract_base import require
from .contract_composition_validation import bundle_sentences
from .contract_context import ContractContext
from .contract_references import references, unique
from .contract_rendering import count_characters, render_body
from .contract_sources import LengthPolicy


def validate_integration(ctx: ContractContext) -> None:
    """Enforce validate integration boundary semantics."""
    report = ctx.integration_report
    if report is None:
        return
    require(ctx.bundle is not None, "missing_context", "Integration requires current candidate")
    if ctx.bundle is None:
        return
    require(
        report.evidence_version == report.baseline_bundle.evidence_version == ctx.evidence_version,
        "evidence_version",
        "integration",
    )
    require(
        report.candidate_version_id == ctx.bundle.version_id,
        "candidate_version",
        "Integration must identify current candidate",
    )
    if ctx.writing_report is not None:
        require(
            report.source_draft_id == ctx.writing_report.draft_id,
            "source_draft",
            "Integration must identify writing report",
        )
        original_sentences = {
            s.sentence_id: s
            for draft in ctx.section_drafts
            for allocation in draft.allocations
            for s in allocation.sentences
        }
        if not original_sentences and bundle_sentences(report.baseline_bundle):
            original_sentences = {
                sentence.sentence_id: sentence for sentence in ctx.writing_report.fallback_sentences
            }
        require(
            {s.sentence_id: s for s in bundle_sentences(report.baseline_bundle)}
            == original_sentences,
            "baseline_source",
            "Integration baseline must preserve the supplied writing-stage sentences",
        )
    _validate_edits(ctx)
    require(
        report.selection != "general_fallback"
        or all(edit.operation in ("delete", "add_fallback") for edit in report.edits),
        "fallback_replacement",
        "General fallback replaces all prior content rather than supplementing it",
    )
    before = {s.sentence_id: s for s in bundle_sentences(report.baseline_bundle)}
    after = {s.sentence_id: s for s in bundle_sentences(ctx.bundle)}
    if report.selection == "baseline":
        require(
            ctx.bundle == report.baseline_bundle,
            "baseline_selection",
            "Selected baseline must be preserved",
        )

    for row in report.reverse_outline:
        selected = report.baseline_bundle if row.scope == "baseline" else ctx.bundle
        paragraphs = {p.paragraph_id: p for p in selected.paragraphs}
        references((row.paragraph_id,), paragraphs, "reverse paragraph")
        references(
            row.sentence_ids,
            (s.sentence_id for s in paragraphs[row.paragraph_id].sentences),
            "reverse sentences",
        )
        require(
            row.semantic_status != "unassessed"
            or (
                row.gist is None
                and not row.roles
                and not row.requirement_ids
                and row.difference_from_plan is None
            ),
            "reverse_semantics",
            "Unassessed summaries cannot carry stale semantic claims",
        )
    for check in report.requirement_checks:
        references(check.baseline_sentence_ids, before, "integration prior sentences")
        references(check.candidate_sentence_ids, after, "integration current sentences")
    for bundle, snapshot in (
        (report.baseline_bundle, report.length_before),
        (ctx.bundle, report.length_after),
    ):
        policy = LengthPolicy(
            max_chars=snapshot.max_chars,
            include_spaces=snapshot.include_spaces,
            include_newlines=snapshot.include_newlines,
            include_subtitle=snapshot.include_subtitle,
        )
        require(
            count_characters(render_body(bundle), policy) == snapshot.body_chars,
            "length_measurement",
            "Integration count must match actual body",
        )


def _validate_edits(ctx: ContractContext) -> None:
    if ctx.integration_report is None or ctx.bundle is None:
        return
    report = ctx.integration_report
    before = {s.sentence_id: s for s in bundle_sentences(report.baseline_bundle)}
    after = {s.sentence_id: s for s in bundle_sentences(ctx.bundle)}
    before_trace = tuple(sid for edit in report.edits for sid in edit.before_sentence_ids)
    after_trace = tuple(sid for edit in report.edits for sid in edit.after_sentence_ids)
    require(
        unique(before_trace, "before edit mapping") == set(before),
        "edit_trace",
        "Every baseline sentence must be mapped",
    )
    require(
        unique(after_trace, "after edit mapping") == set(after),
        "edit_trace",
        "Every candidate sentence must be mapped",
    )
    for edit in report.edits:
        if edit.operation in ("retain", "move"):
            require(
                edit.before_sentence_ids == edit.after_sentence_ids
                and all(before[sid] == after[sid] for sid in edit.before_sentence_ids),
                "edit_identity",
                "Retained/moved sentences preserve content and ID",
            )
        if edit.operation in ("rewrite", "merge", "split"):
            require(
                bool(edit.before_sentence_ids)
                and bool(edit.after_sentence_ids)
                and not set(edit.before_sentence_ids).intersection(edit.after_sentence_ids),
                "edit_identity",
                "Changed sentences require new IDs",
            )
        if edit.operation == "delete":
            require(
                bool(edit.before_sentence_ids) and not edit.after_sentence_ids,
                "delete_mapping",
                "Delete has only prior sentences",
            )
        if edit.operation in ("add_grounded", "add_connective", "add_fallback"):
            require(
                not edit.before_sentence_ids and bool(edit.after_sentence_ids),
                "add_mapping",
                "Add has only new sentences",
            )
        if edit.operation == "add_fallback":
            require(
                report.selection == "general_fallback"
                and not edit.section_ids
                and not edit.fact_ids
                and all(
                    not after[sid].fact_ids
                    and not after[sid].section_ids
                    and after[sid].claim_kind == "general_statement"
                    for sid in edit.after_sentence_ids
                ),
                "fallback_edit",
                "Fallback edits are explicit general replacements",
            )
