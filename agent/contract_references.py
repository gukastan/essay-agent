"""Public contract_references boundary contracts."""

from collections.abc import Iterable
from typing import Final

from .contract_base import require
from .contract_context import ContractContext
from .contract_sources import validate_request_parent

TOTAL_WEIGHT: Final = 100


def unique(values: Iterable[str], label: str) -> set[str]:
    """Enforce unique boundary semantics."""
    items = tuple(values)
    require(len(items) == len(set(items)), "duplicate_id", label)
    require(all(items), "empty_id", label)
    return set(items)


def references(values: Iterable[str], known: Iterable[str], label: str) -> None:
    """Enforce references boundary semantics."""
    require(set(values) <= set(known), "unknown_reference", label)


def validate_sources(ctx: ContractContext) -> None:
    """Enforce validate sources boundary semantics."""
    sources = {source.source_id: source for source in ctx.sources}
    _ = unique((source.source_id for source in ctx.sources), "sources")
    fact_ids = unique((fact.fact_id for fact in ctx.facts), "facts")
    for source in ctx.sources:
        require(source.evidence_version == ctx.evidence_version, "evidence_version", "source")
    for fact in ctx.facts:
        references((fact.source_id,), sources, "fact.source_id")
        source = sources[fact.source_id]
        require(fact.source_kind == source.source_kind, "source_kind", "fact/source mismatch")
        require(
            fact.span.end <= len(source.text)
            and source.text[fact.span.start : fact.span.end] == fact.quote,
            "source_span",
            "Quote must exactly match preserved source span",
        )
        require(
            fact.claim_kind not in ("personal_event", "stated_view")
            or source.source_kind == "applicant",
            "personal_source",
            "Personal claims require applicant sources",
        )
        references(fact.conflict_ids, fact_ids, "fact.conflict_ids")
    if ctx.request is not None:
        validate_request_parent(ctx.request, ctx.parent)
        _ = unique(
            (
                s.source_id
                for s in (
                    *ctx.request.experiences,
                    *ctx.request.user_views,
                    *ctx.request.company_sources,
                )
            ),
            "request.sources",
        )
    if ctx.revision_context is not None:
        registry = ctx.revision_context.question_registry
        _ = unique((entry.question_key for entry in registry), "question_registry")
        history_sources = {entry.source_id for entry in ctx.revision_context.source_history}
        for entry in registry:
            references(
                entry.subject_source_ids,
                set(sources) | history_sources,
                "question.subject_source_ids",
            )
            if entry.user_response_source_id is not None:
                references(
                    (entry.user_response_source_id,),
                    set(sources) | history_sources,
                    "question.response_source",
                )
        if ctx.request is not None:
            references(
                (update.question_key for update in ctx.request.question_updates),
                (entry.question_key for entry in registry),
                "question_updates",
            )


def validate_analysis(ctx: ContractContext) -> None:
    """Enforce validate analysis boundary semantics."""
    analysis = ctx.analysis
    if analysis is None:
        return
    facts = {fact.fact_id: fact for fact in ctx.facts}
    requirements = {item.requirement_id: item for item in analysis.requirements}
    _ = unique((item.requirement_id for item in analysis.requirements), "requirements")
    experiences = unique(
        (item.experience_id for item in analysis.experience_candidates), "experiences"
    )
    candidates = unique((item.candidate_id for item in analysis.answer_candidates), "candidates")
    candidate_map = {item.candidate_id: item for item in analysis.answer_candidates}
    _ = unique((item.gap_id for item in analysis.gaps), "gaps")
    require(
        not experiences.intersection(candidates),
        "candidate_identity",
        "Candidate and experience IDs are distinct",
    )
    _validate_candidates(ctx)
    for link in analysis.evidence_links:
        references((link.requirement_id,), requirements, "evidence.requirement")
        references((link.candidate_id,), candidates, "evidence.candidate")
        references(
            link.fact_ids, candidate_map[link.candidate_id].fact_ids, "evidence candidate facts"
        )
        require(
            not requirements[link.requirement_id].required_by_prompt
            or link.applicability == "applies",
            "required_applicability",
            "Required prompt items remain applicable when evidence is missing",
        )
    for gap in analysis.gaps:
        references(gap.requirement_ids, requirements, "gap.requirements")
        if gap.candidate_id is not None:
            references((gap.candidate_id,), candidates, "gap.candidate")
    for held in analysis.held_claims:
        references(held.fact_ids, facts, "held.fact_ids")
        references(held.requirement_ids, requirements, "held.requirements")
    for claim in (
        *analysis.company_role_context,
        *analysis.competency_candidates,
        *analysis.role_links,
    ):
        references(claim.fact_ids, facts, "context.fact_ids")
    if ctx.request is not None and ctx.request.question and analysis.analysis_status != "complete":
        require(
            any(
                r.requirement_id == "R-unparsed-question"
                and r.description == ctx.request.question
                and r.resolution == "unparsed"
                and r.origin == "explicit"
                and r.required_by_prompt
                and r.information_role == "direct"
                for r in analysis.requirements
            ),
            "unparsed_question",
            "Incomplete analysis must preserve the full question",
        )


def _validate_candidates(ctx: ContractContext) -> None:
    if ctx.analysis is None:
        return
    analysis = ctx.analysis
    facts = {f.fact_id: f for f in ctx.facts}
    experiences = {e.experience_id for e in analysis.experience_candidates}
    requirements = {r.requirement_id for r in analysis.requirements}
    for fact in ctx.facts:
        if fact.experience_id is not None:
            references((fact.experience_id,), experiences, "fact.experience_id")
    for experience in analysis.experience_candidates:
        references(experience.fact_ids, facts, "experience.fact_ids")
        require(
            all(
                facts[fid].experience_id == experience.experience_id for fid in experience.fact_ids
            ),
            "experience_attribution",
            "Event facts retain their event identity",
        )
    for candidate in analysis.answer_candidates:
        references(candidate.fact_ids, facts, "candidate.fact_ids")
        references(candidate.experience_ids, experiences, "candidate.experience_ids")
        references(candidate.requirement_ids, requirements, "candidate.requirement_ids")
        references(
            (
                event
                for fid in candidate.fact_ids
                if (event := facts[fid].experience_id) is not None
            ),
            candidate.experience_ids,
            "candidate events",
        )
