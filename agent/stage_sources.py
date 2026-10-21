"""Freeze active input and bounded MCP results before the analysis call."""

from dataclasses import dataclass
from typing import Final

import anyio

from .contracts import (
    EssayRequest,
    EvidenceVersion,
    RevisionContext,
    SourceId,
    SourceMetadata,
    SourceSnapshot,
    UserSource,
)
from .deps import EssayMaterials
from .stage_analysis_models import AnalysisPayload

RESEARCH_SECONDS: Final = 15


@dataclass(frozen=True, slots=True)
class SourceInput:
    """Run identity and server-owned revision context for source preparation."""

    request: EssayRequest
    evidence_version: EvidenceVersion
    revision_context: RevisionContext


def user_source_id(source_id: str) -> SourceId:
    """Separate caller identifiers from the MCP namespace without altering text."""
    return SourceId(f"user:{source_id}")


def active_sources(run: SourceInput) -> tuple[SourceSnapshot, ...]:
    """Use the current form only; revision instructions are never facts."""
    request = run.request
    entries = [(source, "applicant") for source in (*request.experiences, *request.user_views)]
    entries += [(source, "company") for source in request.company_sources]
    if request.job_posting_text:
        entries.append(
            (
                UserSource(source_id=SourceId("field:job_posting"), text=request.job_posting_text),
                "job_posting",
            )
        )
    return tuple(
        SourceSnapshot.model_validate(
            {
                "source_id": SourceId("field:job_posting")
                if kind == "job_posting"
                else user_source_id(source.source_id),
                "evidence_version": run.evidence_version,
                "source_kind": kind,
                "text": source.text,
                "source_order": order,
                "metadata": SourceMetadata(
                    origin="user", label=source.source_id, uri=None, catalog=None
                ),
            }
        )
        for order, (source, kind) in enumerate(entries)
    )


async def prepare_analysis(run: SourceInput, mcp: EssayMaterials | None) -> AnalysisPayload:
    """Read external materials once; missing research cannot prevent analysis."""
    sources = active_sources(run)
    payload = AnalysisPayload(
        request=run.request,
        evidence_version=run.evidence_version,
        sources=sources,
        revision_context=run.revision_context,
        research_status="not_requested",
    )
    company = (run.request.company_name or "").strip()
    if not company or run.request.company_sources:
        return payload
    if mcp is None:
        return payload.model_copy(update={"research_status": "unavailable"})
    try:
        with anyio.fail_after(RESEARCH_SECONDS):
            materials = await mcp.search_company_job_materials(company, run.request.job_title)
    except (TimeoutError, OSError):
        return payload.model_copy(update={"research_status": "unavailable"})
    external = tuple(
        material.snapshot(run.evidence_version, len(sources) + index)
        for index, material in enumerate(materials[:3])
    )
    return payload.model_copy(
        update={
            "sources": sources + external,
            "research_status": "available" if external else "unavailable",
        }
    )
