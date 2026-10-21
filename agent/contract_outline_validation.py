"""Outline reference and budget validation."""

from typing import Final

from .contract_base import require
from .contract_context import ContractContext
from .contract_references import references, unique

TOTAL_WEIGHT: Final = 100


def validate_outline(ctx: ContractContext) -> None:
    """Enforce validate outline boundary semantics."""
    outline = ctx.outline
    if outline is None:
        return
    require(ctx.analysis is not None, "missing_context", "Outline requires analysis")
    if ctx.analysis is None:
        return
    analysis = ctx.analysis
    facts = {fact.fact_id for fact in ctx.facts}
    requirements = {item.requirement_id: item for item in analysis.requirements}
    gaps = {item.gap_id for item in analysis.gaps}
    sections = {item.section_id: item for item in outline.sections}
    _ = unique((item.section_id for item in outline.sections), "sections")
    _ = unique((item.paragraph_id for item in outline.paragraphs), "paragraphs")
    _ = unique((str(item.order) for item in outline.paragraphs), "paragraph order")
    require(outline.evidence_version == ctx.evidence_version, "evidence_version", "outline")
    references(
        outline.selected_candidate_ids,
        (c.candidate_id for c in analysis.answer_candidates),
        "selected candidates",
    )
    references(
        outline.selected_experience_ids,
        (e.experience_id for e in analysis.experience_candidates),
        "selected experiences",
    )
    references(outline.core_answer_fact_ids, facts, "core answer")
    selected = [
        c for c in analysis.answer_candidates if c.candidate_id in outline.selected_candidate_ids
    ]
    require(
        set(outline.selected_experience_ids) == {eid for c in selected for eid in c.experience_ids},
        "selected_events",
        "Selected events must come from selected answer candidates",
    )
    require(
        set(outline.selected_candidate_ids)
        == {d.candidate_id for d in outline.selection_decisions if d.decision == "selected"},
        "selected_decisions",
        "Selection decisions must agree with selected candidates",
    )
    fact_map = {fact.fact_id: fact for fact in ctx.facts}
    references(outline.subtitle_plan.fact_ids, facts, "subtitle plan")
    for decision in outline.selection_decisions:
        references(
            (decision.candidate_id,),
            (c.candidate_id for c in analysis.answer_candidates),
            "decision candidate",
        )
        references(decision.requirement_ids, requirements, "decision requirements")
    for section in outline.sections:
        references(section.fact_ids, facts, "section facts")
        references(section.experience_ids, outline.selected_experience_ids, "section experiences")
        references(section.requirement_ids, requirements, "section requirements")
        references(section.gap_ids, gaps, "section gaps")
        references(
            (
                event
                for fid in section.fact_ids
                if (event := fact_map[fid].experience_id) is not None
            ),
            section.experience_ids,
            "section event attribution",
        )
    for mapping in outline.requirement_map:
        references((mapping.requirement_id,), requirements, "requirement map")
        references(mapping.section_ids, sections, "requirement sections")
        references(mapping.gap_ids, gaps, "requirement gaps")
        require(
            not requirements[mapping.requirement_id].required_by_prompt
            or mapping.planned_coverage != "not_applicable",
            "required_applicability",
            "Required item cannot be not applicable",
        )
    require(
        {m.requirement_id for m in outline.requirement_map} == set(requirements),
        "requirement_map",
        "Every requirement must remain represented",
    )
    for paragraph in outline.paragraphs:
        for allocation in paragraph.allocations:
            references((allocation.section_id,), sections, "paragraph.section")
            section = sections[allocation.section_id]
            references(allocation.fact_ids, section.fact_ids, "allocation fact outside section")
            require(
                section.write_mode != "omit"
                or (
                    paragraph.weight == 0
                    and paragraph.target_chars in (None, 0)
                    and not allocation.content_focus.strip()
                ),
                "omit_budget",
                "Omitted sections cannot receive content or positive budget",
            )
        if paragraph.previous_relation is not None:
            references(paragraph.previous_relation.fact_ids, facts, "paragraph relation")
        require(
            outline.budget.max_chars is not None or paragraph.target_chars is None,
            "unknown_budget",
            "Unknown limits keep targets null",
        )
    if outline.paragraphs:
        require(
            sum(p.weight for p in outline.paragraphs) == TOTAL_WEIGHT,
            "paragraph_weights",
            "Writing weights sum to 100",
        )
    require(
        outline.budget.max_chars is not None or outline.budget.usable_body_chars is None,
        "unknown_budget",
        "Unknown body budget is null",
    )
