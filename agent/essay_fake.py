"""Explicit current-payload response factory for offline workflow tests."""

from typing import assert_never

from .contracts import ContractModel
from .essay_llm import ErrorKind, GenerationError, GenerationUsage, Output, Stage
from .fake_analysis import analyze_literals
from .fake_composition import integrate_literals, write_literals
from .fake_repair import repair_literals
from .fake_review import review_literals
from .stage_analysis_models import AnalysisPayload
from .stage_integration_models import IntegrationPayload
from .stage_review_models import RepairPayload, ReviewPayload
from .stage_structure_models import StructureOutput, StructurePayload
from .stage_structure_rules import structure_fallback
from .stage_writing_models import WritingPayload


def essay_response(stage: Stage, payload: ContractModel, output_model: type[Output]) -> Output:
    """No cached examples, facts, mutable history or forced failures are used."""
    match stage:
        case "analyze_context":
            analysis_payload = AnalysisPayload.model_validate(payload.model_dump())
            response: ContractModel = analyze_literals(analysis_payload)
        case "plan_structure":
            structure_payload = StructurePayload.model_validate(payload.model_dump())
            response = StructureOutput(outline=structure_fallback(structure_payload))
        case "write_sections":
            response = write_literals(WritingPayload.model_validate(payload.model_dump()))
        case "integrate_draft":
            response = integrate_literals(IntegrationPayload.model_validate(payload.model_dump()))
        case "title_and_review":
            response = review_literals(ReviewPayload.model_validate(payload.model_dump()))
        case "repair_draft":
            response = repair_literals(RepairPayload.model_validate(payload.model_dump()))
        case "deliver_result":
            raise GenerationError(ErrorKind.CONFIGURATION, GenerationUsage(attempts=()))
        case _:
            assert_never(stage)
    return output_model.model_validate(response.model_dump())
