"""Current-input literal writing and identity integration for offline mode."""

from .composition_rules import new_version
from .contracts import DraftAllocation, SectionDraft, Sentence, SentenceId
from .fake_integration import merge_exact_repetitions
from .stage_integration_models import IntegrationOutput, IntegrationPayload
from .stage_integration_records import (
    structural_reverse,
    unassessed_requirements,
)
from .stage_writing_models import WritingOutput, WritingPayload


def write_literals(payload: WritingPayload) -> WritingOutput:
    """Quote only current allocated facts and never fill missing personal information."""
    facts = {fact.fact_id: fact for fact in payload.facts}
    drafts: list[SectionDraft] = []
    for section in payload.outline.sections:
        allocations: list[DraftAllocation] = []
        if section.write_mode != "omit":
            for paragraph in payload.outline.paragraphs:
                for allocation in paragraph.allocations:
                    if allocation.section_id != section.section_id:
                        continue
                    sentences = tuple(
                        Sentence(
                            sentence_id=SentenceId(f"sentence:{new_version()}"),
                            text=facts[fid].quote,
                            section_ids=(section.section_id,),
                            claim_kind=facts[fid].claim_kind,
                            fact_ids=(fid,),
                        )
                        for fid in allocation.fact_ids
                    )
                    if section.write_mode == "general":
                        sentences = (
                            Sentence(
                                sentence_id=SentenceId(f"sentence:{new_version()}"),
                                text="협업은 서로 다른 역할과 관점이 만나는 과정입니다.",
                                section_ids=(section.section_id,),
                                claim_kind="general_statement",
                                fact_ids=(),
                            ),
                        )
                    allocations.append(
                        DraftAllocation(
                            planned_paragraph_id=paragraph.paragraph_id, sentences=sentences
                        )
                    )
        drafts.append(SectionDraft(section_id=section.section_id, allocations=tuple(allocations)))
    return WritingOutput(
        section_drafts=tuple(drafts), notes=(), section_checks=(), personalization="partial"
    )


def integrate_literals(payload: IntegrationPayload) -> IntegrationOutput:
    """Retain current prose with exhaustive identity trace; infer no semantic certification."""
    baseline = payload.baseline_bundle
    paragraphs, edits = merge_exact_repetitions(baseline)
    candidate = baseline.model_copy(update={"paragraphs": paragraphs})
    return IntegrationOutput(
        paragraphs=paragraphs,
        edits=edits,
        reverse_outline=structural_reverse(baseline, "baseline")
        + structural_reverse(candidate, "candidate"),
        requirement_checks=unassessed_requirements(
            baseline, candidate, payload.analysis, payload.outline
        ),
        issues=(),
    )
