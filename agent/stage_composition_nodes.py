"""Execute writing and integration once each with typed conservative recovery."""

from __future__ import annotations

from typing import TYPE_CHECKING

from .composition_rules import assembled_paragraphs, general_fallback, new_version
from .contract_base import ContractViolation
from .contracts import (
    ContractModel,
    DraftBundle,
    DraftParagraph,
    ParagraphId,
    SentenceId,
    validate_contract,
)
from .essay_llm import GenerationError
from .stage_integration_contract import integration_context
from .stage_integration_models import IntegrationOutput, IntegrationPayload
from .stage_integration_selection import restore_baseline, select_integration
from .stage_issues import generation_issue
from .stage_writing_cleanup import merge_partial
from .stage_writing_models import WritingOutput, WritingPayload, WritingRecovery, writing_context
from .stage_writing_report import finish_writing

if TYPE_CHECKING:
    from .deps import SupervisorDeps
    from .graph_state import EssayState, EssayUpdate


def writing_payload(state: EssayState) -> WritingPayload:
    """Load only current immutable source/analysis/outline fields from graph state."""
    analysis, outline = state.get("analysis"), state.get("outline")
    if analysis is None or outline is None:
        msg = "writing_context"
        raise ContractViolation(msg, "Writing requires analysis and outline")
    return WritingPayload(
        request=state["request"],
        evidence_version=state["evidence_version"],
        sources=state.get("sources", ()),
        facts=state.get("facts", ()),
        analysis=analysis,
        outline=outline,
    )


async def write_sections(state: EssayState, deps: SupervisorDeps) -> EssayUpdate:
    """Preserve validated parsed parts across the adapter's original two attempts."""
    payload = writing_payload(state)
    partial: WritingRecovery | None = None

    def recover(parsed: ContractModel, payload: ContractModel) -> ContractModel | None:
        """Keep the collector local to this single logical generation call."""
        nonlocal partial
        if not isinstance(parsed, WritingOutput):
            return None
        partial = merge_partial(partial, parsed, WritingPayload.model_validate(payload))
        return partial

    issues = state.get("technical_issues", ())
    history: tuple[SentenceId, ...] = ()
    try:
        generated = await deps.quality_llm.generate(
            "write_sections", payload, WritingOutput, recover=recover
        )
        output, usage = generated.output, generated.usage
    except GenerationError as error:
        usage = error.usage
        issues += (generation_issue("write_sections", error),)
        if isinstance(error.recovered, WritingRecovery):
            recovered = error.recovered
            output = recovered
            history = recovered.original_sentence_ids
        else:
            output = WritingOutput(
                section_drafts=(),
                notes=(),
                section_checks=(),
                personalization="non_personalized",
            )
    clean, report = finish_writing(output, payload, history)
    validate_contract(
        writing_context(payload).model_copy(
            update={"section_drafts": clean.section_drafts, "writing_report": report}
        )
    )
    return {
        "section_drafts": clean.section_drafts,
        "writing_report": report,
        "technical_issues": issues,
        "usage": (*state.get("usage", ()), usage),
    }


def integration_payload(state: EssayState) -> IntegrationPayload:
    """Build an immutable baseline from current section allocations or explicit fallback."""
    payload = writing_payload(state)
    report = state.get("writing_report")
    if report is None:
        msg = "writing_report"
        raise ContractViolation(msg, "Integration requires a writing report")
    drafts = state.get("section_drafts", ())
    paragraphs = assembled_paragraphs(drafts, payload.outline)
    if not paragraphs:
        paragraphs = (
            DraftParagraph(
                paragraph_id=ParagraphId("fallback"),
                sentences=report.fallback_sentences or general_fallback(),
            ),
        )
    baseline = DraftBundle(
        version_id=report.draft_id,
        evidence_version=payload.evidence_version,
        paragraphs=paragraphs,
        subtitle=None,
        subtitle_fact_ids=(),
        subtitle_placement="answer",
        personalization=report.personalization,
    )
    return IntegrationPayload(
        request=payload.request,
        evidence_version=payload.evidence_version,
        sources=payload.sources,
        facts=payload.facts,
        analysis=payload.analysis,
        outline=payload.outline,
        section_drafts=drafts,
        writing_report=report,
        baseline_bundle=baseline,
        candidate_version_id=new_version(),
    )


async def integrate_draft(state: EssayState, deps: SupervisorDeps) -> EssayUpdate:
    """Select one complete edit proposal or restore a safe copy without extra quality calls."""
    payload = integration_payload(state)
    issues = state.get("technical_issues", ())
    try:
        generated = await deps.quality_llm.generate("integrate_draft", payload, IntegrationOutput)
        bundle, report = select_integration(payload, generated.output)
        usage = generated.usage
    except GenerationError as error:
        bundle, report = restore_baseline(payload, ())
        usage = error.usage
        issues += (generation_issue("integrate_draft", error),)
    validate_contract(integration_context(payload, bundle, report))
    return {
        "candidate_bundle": bundle,
        "integration_report": report,
        "technical_issues": issues,
        "usage": (*state.get("usage", ()), usage),
    }
