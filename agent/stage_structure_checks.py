"""Keep selected evidence and requirement coverage consistent at the planning boundary."""

from .contract_base import require
from .contracts import Analysis, Fact, Outline
from .stage_evidence import eligible_links


def validate_usable_content(outline: Outline, analysis: Analysis, facts: tuple[Fact, ...]) -> None:
    """Reject existing IDs whose information or use status disallows writing."""
    links = eligible_links(analysis, facts)
    eligible = {
        fact_id
        for link in links
        if link.candidate_id in outline.selected_candidate_ids
        for fact_id in link.fact_ids
    }
    require(
        set(outline.core_answer_fact_ids) <= eligible,
        "core_evidence",
        "Core uses selected evidence",
    )
    require(
        set(outline.subtitle_plan.fact_ids) <= eligible,
        "subtitle_evidence",
        "Title uses selected evidence",
    )
    for section in outline.sections:
        require(
            set(section.fact_ids) <= eligible, "section_evidence", "Section uses selected evidence"
        )
        if section.write_mode == "grounded":
            require(
                bool(section.fact_ids), "grounded_evidence", "Grounded sections require evidence"
            )
        if section.write_mode == "general":
            require(
                not section.experience_ids,
                "general_event",
                "General content is not a personal event",
            )
    requirements = {item.requirement_id: item for item in analysis.requirements}
    sections = {item.section_id: item for item in outline.sections}
    gaps = {item.gap_id: item for item in analysis.gaps}
    for mapping in outline.requirement_map:
        for section_id in mapping.section_ids:
            require(
                mapping.requirement_id in sections[section_id].requirement_ids,
                "section_requirement",
                "Requirement placement must be reciprocal",
            )
        for gap_id in mapping.gap_ids:
            require(
                mapping.requirement_id in gaps[gap_id].requirement_ids,
                "gap_requirement",
                "A gap must describe the mapped requirement",
            )
        if requirements[mapping.requirement_id].resolution == "unparsed":
            require(
                mapping.planned_coverage == "unfilled",
                "unparsed_coverage",
                "Unparsed requirements remain unassessed",
            )
        if mapping.planned_coverage == "planned_supported":
            supported = {
                fact_id
                for link in links
                if link.requirement_id == mapping.requirement_id
                and link.candidate_id in outline.selected_candidate_ids
                for fact_id in link.fact_ids
            } & eligible
            require(
                any(supported.intersection(sections[sid].fact_ids) for sid in mapping.section_ids),
                "supported_coverage",
                "Planned support requires current linked evidence",
            )
