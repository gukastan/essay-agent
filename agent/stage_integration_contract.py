"""Validate an integration proposal against the immutable baseline and evidence."""

from __future__ import annotations

from typing import TYPE_CHECKING

from .composition_rules import length_snapshot, personalization_for
from .contract_base import require
from .contract_composition_validation import bundle_sentences
from .contracts import ContractContext, DraftBundle, IntegrationReport, validate_contract
from .stage_evidence import eligible_links
from .stage_integration_completion import complete_requirements, complete_reverse

if TYPE_CHECKING:
    from .stage_integration_data import IntegrationPayload, IntegrationProposal


def proposed_pair(
    payload: IntegrationPayload, output: IntegrationProposal
) -> tuple[DraftBundle, IntegrationReport]:
    """Attach server identity, actual measurements and the model's explicit comparison."""
    paragraphs = tuple(paragraph for paragraph in output.paragraphs if paragraph.sentences)
    bundle = DraftBundle(
        version_id=payload.candidate_version_id,
        evidence_version=payload.evidence_version,
        paragraphs=paragraphs,
        subtitle=None,
        subtitle_fact_ids=(),
        subtitle_placement="answer",
        personalization=personalization_for(
            paragraphs, payload.facts, payload.analysis, payload.outline
        ),
    )
    report = IntegrationReport(
        source_draft_id=payload.writing_report.draft_id,
        evidence_version=payload.evidence_version,
        baseline_bundle=payload.baseline_bundle,
        candidate_version_id=bundle.version_id,
        selection="edited",
        selection_reason="원문 범위의 통합 제안을 채택했습니다.",
        edits=output.edits,
        reverse_outline=complete_reverse(output, bundle),
        requirement_checks=complete_requirements(output, payload, bundle),
        length_before=length_snapshot(payload.baseline_bundle, payload.request.length_policy),
        length_after=length_snapshot(bundle, payload.request.length_policy),
        issues=output.issues,
    )
    return bundle, report


def integration_context(
    payload: IntegrationPayload, bundle: DraftBundle, report: IntegrationReport
) -> ContractContext:
    """Build one complete shared validation context without mutating input records."""
    return ContractContext(
        evidence_version=payload.evidence_version,
        sources=payload.sources,
        facts=payload.facts,
        analysis=payload.analysis,
        outline=payload.outline,
        section_drafts=payload.section_drafts,
        writing_report=payload.writing_report,
        bundle=bundle,
        integration_report=report,
    )


def validate_proposal(payload: IntegrationPayload, output: IntegrationProposal) -> None:
    """Reject reference/identity changes within the adapter's shared attempt budget."""
    bundle, report = proposed_pair(payload, output)
    validate_contract(integration_context(payload, bundle, report))
    eligible = {
        fid for link in eligible_links(payload.analysis, payload.facts) for fid in link.fact_ids
    }
    for sentence in bundle_sentences(bundle):
        require(
            set(sentence.fact_ids) <= eligible,
            "integration_fact",
            "Only current available facts can be used",
        )
    before = {s.sentence_id: s for s in bundle_sentences(payload.baseline_bundle)}
    after = {s.sentence_id: s for s in bundle_sentences(bundle)}
    for sid in set(before) & set(after):
        require(before[sid] == after[sid], "changed_sentence_id", "Changed prose needs a new ID")
    for issue in output.issues:
        valid_ids = before if issue.scope == "baseline" else after
        require(
            set(issue.sentence_ids) <= set(valid_ids),
            "issue_sentence",
            "Issue references its declared version",
        )
    require(
        len({row.requirement_id for row in output.requirement_checks})
        == len(output.requirement_checks),
        "duplicate_requirement_check",
        "One integration comparison per requirement",
    )

    section_ids = {s.section_id for s in payload.outline.sections}
    fact_ids = {f.fact_id for f in payload.facts}
    requirement_ids = {r.requirement_id for r in payload.analysis.requirements}
    gap_ids = {g.gap_id for g in payload.analysis.gaps}
    for issue in output.issues:
        require(
            set(issue.section_ids) <= section_ids
            and set(issue.requirement_ids) <= requirement_ids
            and set(issue.gap_ids) <= gap_ids,
            "integration_issue_refs",
            "Issue must use current references",
        )
    for edit in output.edits:
        require(
            set(edit.section_ids) <= section_ids and set(edit.fact_ids) <= fact_ids,
            "integration_edit_refs",
            "Edit must use current references",
        )
    for row in output.reverse_outline:
        selected = payload.baseline_bundle if row.scope == "baseline" else bundle
        paragraph = next(p for p in selected.paragraphs if p.paragraph_id == row.paragraph_id)
        require(
            set(row.sentence_ids) == {s.sentence_id for s in paragraph.sentences}
            and set(row.section_ids) == {sid for s in paragraph.sentences for sid in s.section_ids}
            and set(row.fact_ids) == {fid for s in paragraph.sentences for fid in s.fact_ids}
            and set(row.requirement_ids) <= requirement_ids,
            "integration_reverse_refs",
            "Reverse outline must describe actual current sentences",
        )
    for check in output.requirement_checks:
        require(
            check.requirement_id in requirement_ids and set(check.gap_ids) <= gap_ids,
            "integration_requirement_refs",
            "Comparison must use current requirements",
        )
