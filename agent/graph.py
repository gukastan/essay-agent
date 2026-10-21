"""Essay stages reuse StateGraph, async nodes and explicit partial injection."""

from functools import partial
from typing import Literal, assert_never

from .contract_base import ContractViolation
from .contracts import (
    ContractContext,
    validate_contract,
)
from .deps import SupervisorDeps
from .essay_llm import GenerationError
from .graph_state import EssayState, EssayUpdate
from .langgraph_boundary import END, START, CompiledGraph, StateGraph
from .mcp_materials import local_guide, local_prompt
from .stage_analysis_models import AnalysisOutput
from .stage_analysis_rules import analysis_fallback, normalize_analysis
from .stage_composition_nodes import integrate_draft, write_sections
from .stage_delivery import deliver_result
from .stage_issues import generation_issue
from .stage_review_nodes import repair_draft, title_and_review
from .stage_sources import SourceInput, prepare_analysis
from .stage_structure_models import StructureOutput, StructurePayload
from .stage_structure_rules import structure_fallback

__all__ = [
    "EssayState",
    "EssayUpdate",
    "build_graph",
    "deliver_result",
    "integrate_draft",
    "repair_draft",
    "title_and_review",
    "write_sections",
]


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
    *,
    stop_after: Literal["plan_structure", "integrate_draft", "deliver_result"] = "deliver_result",
) -> CompiledGraph[EssayState, EssayUpdate]:
    """Compile the released stages; later tickets extend this same graph in order."""
    builder: StateGraph[EssayState, EssayUpdate] = StateGraph(EssayState)
    _ = builder.add_node("analyze_context", partial(analyze_context, deps=deps))
    _ = builder.add_node("plan_structure", partial(plan_structure, deps=deps))
    _ = builder.add_edge(START, "analyze_context")
    _ = builder.add_edge("analyze_context", "plan_structure")
    match stop_after:
        case "plan_structure":
            _ = builder.add_edge("plan_structure", END)
        case "integrate_draft" | "deliver_result":
            _ = builder.add_node("write_sections", partial(write_sections, deps=deps))
            _ = builder.add_node("integrate_draft", partial(integrate_draft, deps=deps))
            _ = builder.add_edge("plan_structure", "write_sections")
            _ = builder.add_edge("write_sections", "integrate_draft")
            if stop_after == "integrate_draft":
                _ = builder.add_edge("integrate_draft", END)
            else:
                _ = builder.add_node("title_and_review", partial(title_and_review, deps=deps))
                _ = builder.add_node("repair_draft", partial(repair_draft, deps=deps))
                _ = builder.add_node("deliver_result", partial(deliver_result, deps=deps))
                _ = builder.add_edge("integrate_draft", "title_and_review")
                _ = builder.add_conditional_edges(
                    "title_and_review",
                    route_review,
                    {"repair_draft": "repair_draft", "deliver_result": "deliver_result"},
                )
                _ = builder.add_edge("repair_draft", "title_and_review")
                _ = builder.add_edge("deliver_result", END)
        case _:
            assert_never(stop_after)
    return builder.compile()


def route_review(state: EssayState) -> str:
    """Route exclusively from the current review control; older warnings cannot stop repair."""
    control = state.get("review_control")
    if control is None:
        code = "review_control"
        raise ContractViolation(code, "Review must determine its next edge")
    return "deliver_result" if control.stop else "repair_draft"
