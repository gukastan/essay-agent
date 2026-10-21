import json
from pathlib import Path

from agent.contracts import ContractContext, EssayResult, validate_contract
from agent.stage_analysis_models import AnalysisOutput, AnalysisPayload
from agent.stage_review_data import ReviewPayload
from agent.stage_structure_models import StructureOutput, StructurePayload
from agent.stage_writing_models import WritingPayload


def validate_trace(directory: Path, result: EssayResult) -> None:
    analysis_input = AnalysisPayload.model_validate_json(
        (directory / "01-analyze_context-payload.json").read_text()
    )
    analysis = AnalysisOutput.model_validate_json(
        (directory / "01-analyze_context-output.json").read_text(),
        context={"payload": analysis_input},
    )
    structure_input = StructurePayload.model_validate_json(
        (directory / "02-plan_structure-payload.json").read_text()
    )
    outline = StructureOutput.model_validate_json(
        (directory / "02-plan_structure-output.json").read_text(),
        context={"payload": structure_input},
    ).outline
    writing = WritingPayload.model_validate_json(
        (directory / "03-write_sections-payload.json").read_text()
    )
    review = ReviewPayload.model_validate_json(
        (directory / "05-title_and_review-payload.json").read_text()
    )
    validate_contract(
        ContractContext(
            evidence_version=analysis_input.evidence_version,
            sources=analysis_input.sources,
            facts=analysis.facts,
            analysis=analysis.analysis,
            outline=outline,
        )
    )
    assert writing.facts == analysis.facts
    assert writing.sources == analysis_input.sources
    assert review.facts == writing.facts
    fact_ids = {fact.fact_id for fact in writing.facts}
    section_ids = {section.section_id for section in outline.sections}
    sentences = tuple(
        sentence
        for paragraph in review.candidate_bundle.paragraphs
        for sentence in paragraph.sentences
    )
    for sentence in sentences:
        assert set(sentence.fact_ids) <= fact_ids
        assert set(sentence.section_ids) <= section_ids
    assert {sid for section in result.structure for sid in section.actual_sentence_ids} <= {
        sentence.sentence_id for sentence in sentences
    }
    assert result.evidence_version == analysis_input.evidence_version
    assert result.character_count == result.quality_report.length_check.counted_chars
    _ = (directory / "source-trace.json").write_text(
        json.dumps(
            {
                "evidence_version": result.evidence_version,
                "result_version": result.version_id,
                "sources": [source.source_id for source in writing.sources],
                "facts": [fact.fact_id for fact in writing.facts],
                "candidates": [
                    candidate.candidate_id for candidate in writing.analysis.answer_candidates
                ],
                "sections": sorted(section_ids),
                "sentences": [sentence.sentence_id for sentence in sentences],
                "characters": result.character_count,
            },
            indent=2,
        )
    )
