"""Essay stages reuse StateGraph, async nodes and explicit partial injection."""

from functools import partial
from typing import TypedDict

from .contract_base import ContractViolation
from .contracts import (
    Analysis,
    ContractContext,
    DraftBundle,
    EssayRequest,
    EvidenceVersion,
    Fact,
    Outline,
    RevisionContext,
    SourceSnapshot,
    TechnicalIssue,
    validate_contract,
)
from .deps import SupervisorDeps
from .essay_llm import GenerationError, GenerationUsage
from .langgraph_boundary import END, START, CompiledGraph, StateGraph
from .mcp_materials import local_guide, local_prompt
from .stage_analysis_models import AnalysisOutput
from .stage_analysis_rules import analysis_fallback, normalize_analysis
from .stage_sources import SourceInput, prepare_analysis
from .stage_structure_models import StructureOutput, StructurePayload
from .stage_structure_rules import structure_fallback


class EssayInput(TypedDict):
    """Server-owned seed required before the first node executes."""

    request: EssayRequest
    evidence_version: EvidenceVersion
    revision_context: RevisionContext


class EssayUpdate(TypedDict, total=False):
    """Node-local updates never replace immutable request context."""

    previous_draft: DraftBundle | None
    sources: tuple[SourceSnapshot, ...]
    facts: tuple[Fact, ...]
    analysis: Analysis
    outline: Outline
    usage: tuple[GenerationUsage, ...]
    technical_issues: tuple[TechnicalIssue, ...]


class EssayState(EssayInput, EssayUpdate):
    """Required run seed plus fields accumulated by the ordered stages."""


def generation_issue(node: str, error: GenerationError) -> TechnicalIssue:
    """Expose only sanitized provider category and actual attempt accounting."""
    return TechnicalIssue(
        node=node,
        code=error.kind.value,
        attempts=len(error.usage.attempts),
        exhausted=error.retryable,
        recovered=True,
        message="모델 단계 오류 후 보존된 입력으로 대체 경로를 사용했습니다.",
    )


async def analyze_context(state: EssayState, deps: SupervisorDeps) -> EssayUpdate:
    """Freeze sources, make one logical fast call, then preserve requirements and gaps."""
    payload = await prepare_analysis(
        SourceInput(
            request=state["request"],
            evidence_version=state["evidence_version"],
            revision_context=state["revision_context"],
        ),
        deps.mcp,
    )
    issues = state.get("technical_issues", ())
    try:
        generated = await deps.fast_llm.generate("analyze_context", payload, AnalysisOutput)
        output = normalize_analysis(generated.output, payload)
        usage = generated.usage
    except GenerationError as error:
        output = analysis_fallback(payload)
        usage = error.usage
        issues += (generation_issue("analyze_context", error),)
    validate_contract(
        ContractContext(
            evidence_version=payload.evidence_version,
            sources=payload.sources,
            facts=output.facts,
            analysis=output.analysis,
        )
    )
    return EssayUpdate(
        sources=payload.sources,
        facts=output.facts,
        analysis=output.analysis,
        technical_issues=issues,
        usage=(*state.get("usage", ()), usage),
    )


async def plan_structure(state: EssayState, deps: SupervisorDeps) -> EssayUpdate:
    """Continue for every information state, using local guides when MCP is absent."""
    analysis = state.get("analysis")
    if analysis is None:
        msg = "analysis_missing"
        raise ContractViolation(msg, "Structure requires the analysis stage")
    question_type = analysis.question_type
    if question_type not in ("experience", "motivation", "strength", "aspiration", "general"):
        question_type = "general"
    guide = local_guide(question_type)
    procedure = local_prompt(question_type)
    if deps.mcp is not None:
        try:
            guide = await deps.mcp.writing_guide(question_type) or guide
            procedure = await deps.mcp.writing_prompt(question_type) or procedure
        except (TimeoutError, OSError):
            guide = local_guide(question_type)
            procedure = local_prompt(question_type)
    payload = StructurePayload(
        request=state["request"],
        evidence_version=state["evidence_version"],
        sources=state.get("sources", ()),
        facts=state.get("facts", ()),
        analysis=analysis,
        guide=guide,
        procedure=procedure,
    )
    issues = state.get("technical_issues", ())
    try:
        generated = await deps.fast_llm.generate("plan_structure", payload, StructureOutput)
        outline = generated.output.outline
        usage = generated.usage
    except GenerationError as error:
        outline = StructureOutput.model_validate(
            {"outline": structure_fallback(payload)}, context={"payload": payload}
        ).outline
        usage = error.usage
        issues += (generation_issue("plan_structure", error),)
    validate_contract(
        ContractContext(
            evidence_version=payload.evidence_version,
            sources=payload.sources,
            facts=payload.facts,
            analysis=payload.analysis,
            outline=outline,
        )
    )
    return EssayUpdate(
        outline=outline, technical_issues=issues, usage=(*state.get("usage", ()), usage)
    )


def build_graph(
    deps: SupervisorDeps,
) -> CompiledGraph[EssayState, EssayUpdate]:
    """Compile the released stages; later tickets extend this same graph in order."""
    builder: StateGraph[EssayState, EssayUpdate] = StateGraph(EssayState)
    _ = builder.add_node("analyze_context", partial(analyze_context, deps=deps))
    _ = builder.add_node("plan_structure", partial(plan_structure, deps=deps))
    _ = builder.add_edge(START, "analyze_context")
    _ = builder.add_edge("analyze_context", "plan_structure")
    _ = builder.add_edge("plan_structure", END)
    return builder.compile()
