"""Check allocation ownership before prose crosses the provider boundary."""

from .contract_base import require
from .contract_composition_validation import validate_sentences
from .contracts import ContractContext, SectionDraft, Sentence
from .stage_evidence import eligible_links


def validate_allocation_sentence(
    sentence: Sentence,
    draft: SectionDraft,
    paragraph_id: str,
    ctx: ContractContext,
) -> None:
    """Keep every claim inside its owning planned allocation and available facts."""
    require(
        ctx.outline is not None and ctx.analysis is not None,
        "writing_context",
        "Outline and analysis required",
    )
    if ctx.outline is None or ctx.analysis is None:
        return
    plans = [
        allocation
        for paragraph in ctx.outline.paragraphs
        if paragraph.paragraph_id == paragraph_id
        for allocation in paragraph.allocations
        if allocation.section_id == draft.section_id
    ]
    require(bool(plans), "allocation_missing", "Writing needs an owning allocation")
    allowed = {fact_id for plan in plans for fact_id in plan.fact_ids}
    eligible = {fid for link in eligible_links(ctx.analysis, ctx.facts) for fid in link.fact_ids}
    require(
        set(sentence.fact_ids) <= allowed & eligible,
        "allocation_facts",
        "Claim exceeds available allocation evidence",
    )
    require(
        draft.section_id in sentence.section_ids,
        "sentence_owner",
        "Sentence retains owning section",
    )
    planned_sections = {
        a.section_id
        for p in ctx.outline.paragraphs
        if p.paragraph_id == paragraph_id
        for a in p.allocations
    }
    require(
        set(sentence.section_ids) <= planned_sections,
        "sentence_sections",
        "Merged sentence stays in planned paragraph",
    )
    validate_sentences((sentence,), ctx, set())


def validate_writing_parts(drafts: tuple[SectionDraft, ...], ctx: ContractContext) -> None:
    """Reject unknown/duplicate sections and references while allowing missing sections."""
    require(ctx.outline is not None, "writing_context", "Outline required")
    if ctx.outline is None:
        return
    sections = {section.section_id: section for section in ctx.outline.sections}
    require(
        len({d.section_id for d in drafts}) == len(drafts),
        "duplicate_section",
        "One draft per section",
    )
    seen: set[str] = set()
    for draft in drafts:
        require(draft.section_id in sections, "unknown_section", "Unknown section")
        require(
            sections[draft.section_id].write_mode != "omit" or not draft.allocations,
            "omit_allocation",
            "Omitted sections carry no prose",
        )
        for allocation in draft.allocations:
            for sentence in allocation.sentences:
                require(
                    sentence.sentence_id not in seen,
                    "duplicate_sentence",
                    "One owning allocation per sentence",
                )
                seen.add(sentence.sentence_id)
                validate_allocation_sentence(sentence, draft, allocation.planned_paragraph_id, ctx)
