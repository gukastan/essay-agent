from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Final

import anyio

from agent.contracts import (
    Analysis,
    ContractModel,
    DraftBundle,
    EssayRequest,
    EvidenceVersion,
    Fact,
    Outline,
    RevisionContext,
    SourceId,
    SourceSnapshot,
    TechnicalIssue,
    UserSource,
)
from agent.deps import EssayMaterials, SupervisorDeps
from agent.essay_fake import essay_response
from agent.essay_llm import ErrorKind, GenerationError, GenerationUsage, Output, Stage
from agent.fake_llm import FastLLM, QualityLLM
from agent.graph import EssayState, build_graph
from agent.stage_analysis_models import AnalysisOutput
from agent.stage_structure_models import StructureOutput

COMMON: Final = (
    "자료 취합을 담당했습니다. 작성 기준 차이로 지연됐습니다. "
    "공통 양식 초안을 만들었습니다. 팀원들의 의견을 반영했습니다. "
    "팀원들은 수정한 양식을 함께 사용했습니다. 자료를 기한 내 취합했습니다."
)
QUESTION: Final = "협업 문제를 해결한 경험을 본인의 역할과 배운 점을 포함하여 설명하세요."


class RunView(ContractModel):
    previous_draft: DraftBundle | None = None
    request: EssayRequest
    evidence_version: EvidenceVersion
    revision_context: RevisionContext
    sources: tuple[SourceSnapshot, ...]
    facts: tuple[Fact, ...]
    analysis: Analysis
    outline: Outline
    usage: tuple[GenerationUsage, ...]
    technical_issues: tuple[TechnicalIssue, ...]


@dataclass(frozen=True, slots=True)
class Responses:
    """Mutable call recording belongs to this test fixture only."""

    analysis_edit: Callable[[AnalysisOutput], AnalysisOutput] | None = None
    structure_edit: Callable[[StructureOutput], StructureOutput] | None = None
    failing_stage: Stage | None = None
    error_kind: ErrorKind = ErrorKind.INCOMPLETE
    calls: list[Stage] = field(default_factory=list)

    def __call__(self, stage: Stage, payload: ContractModel, output_model: type[Output]) -> Output:
        self.calls.append(stage)
        if stage == self.failing_stage:
            raise GenerationError(self.error_kind, GenerationUsage(attempts=()))
        output = essay_response(stage, payload, output_model)
        if stage == "analyze_context" and self.analysis_edit:
            return output_model.model_validate(
                self.analysis_edit(AnalysisOutput.model_validate(output.model_dump())).model_dump()
            )
        if stage == "plan_structure" and self.structure_edit:
            return output_model.model_validate(
                self.structure_edit(
                    StructureOutput.model_validate(output.model_dump())
                ).model_dump()
            )
        return output


def request_for(text: str = COMMON, question: str | None = QUESTION) -> EssayRequest:
    return EssayRequest(
        question=question, experiences=(UserSource(source_id=SourceId("event"), text=text),)
    )


async def execute(
    state: EssayState, responses: Responses, mcp: EssayMaterials | None = None
) -> RunView:
    fast, quality = FastLLM(responses), QualityLLM(responses)
    try:
        graph = build_graph(SupervisorDeps(fast, quality, mcp), stop_after="plan_structure")
        result = await graph.ainvoke(state, {"recursion_limit": 20})
        return RunView.model_validate(result)
    finally:
        await fast.aclose()
        await quality.aclose()


def seed(request: EssayRequest) -> EssayState:
    return EssayState(
        request=request,
        evidence_version=EvidenceVersion("test-evidence"),
        revision_context=RevisionContext(source_history=(), question_registry=()),
    )


def run(request: EssayRequest, responses: Responses | None = None) -> RunView:
    return anyio.run(execute, seed(request), responses or Responses())
