"""Structure output validation against immutable analysis and source snapshots."""

from typing import Self

from pydantic import model_validator

from .contract_base import require
from .contracts import (
    Analysis,
    ContractContext,
    ContractModel,
    EssayRequest,
    EvidenceVersion,
    Fact,
    Outline,
    SourceSnapshot,
    validate_contract,
)
from .essay_rules import budget_outline
from .stage_analysis_models import PayloadValidationInfo
from .stage_structure_checks import validate_usable_content


class StructurePayload(ContractModel):
    """Shared evidence and policy for one complete structure proposal."""

    request: EssayRequest
    evidence_version: EvidenceVersion
    sources: tuple[SourceSnapshot, ...]
    facts: tuple[Fact, ...]
    analysis: Analysis
    guide: str
    procedure: str


class StructureOutput(ContractModel):
    """Model counts are replaced before the proposal crosses the adapter boundary."""

    outline: Outline

    @model_validator(mode="after")
    def current_analysis(self, info: PayloadValidationInfo) -> Self:
        """Run contextual checks within the adapter's original two-attempt budget."""
        if info.context is None:
            return self
        payload = StructurePayload.model_validate(info.context["payload"])
        outline = budget_outline(self.outline, payload.request.length_policy)
        validate_contract(
            ContractContext(
                evidence_version=payload.evidence_version,
                sources=payload.sources,
                facts=payload.facts,
                analysis=payload.analysis,
                outline=outline,
            )
        )
        validate_usable_content(outline, payload.analysis, payload.facts)
        sections = {section.section_id: section for section in outline.sections}
        for paragraph in outline.paragraphs:
            require(bool(paragraph.allocations), "allocation", "Writing paragraphs need content")
            for allocation in paragraph.allocations:
                require(
                    sections[allocation.section_id].write_mode != "omit",
                    "omit_allocation",
                    "Omitted sections have no physical paragraph",
                )
        for mapping in outline.requirement_map:
            require(
                bool(mapping.section_ids), "requirement_section", "Keep every requirement's section"
            )
            if mapping.planned_coverage == "unfilled":
                require(
                    bool(mapping.gap_ids), "requirement_gap", "Unfilled requirements retain gaps"
                )
        personal_ids = {
            fact.fact_id
            for fact in payload.facts
            if fact.source_kind == "applicant" and fact.information_state == "available"
        }
        if not personal_ids.intersection(outline.core_answer_fact_ids):
            require(
                outline.core_answer is None
                and not outline.core_answer_fact_ids
                and bool(outline.general_direction),
                "general_core",
                "No personal evidence means a general direction, not a personal core answer",
            )
        return self.model_copy(update={"outline": outline})
