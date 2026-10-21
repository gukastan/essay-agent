"""Compute source offsets and provisional counts without changing semantic claims."""

from pydantic import TypeAdapter
from typing_extensions import TypeAliasType

from .contract_base import require
from .contracts import (
    Analysis,
    ContractModel,
    Fact,
    SourceSnapshot,
    SourceSpan,
    StrictLengthPolicy,
    count_characters,
)

ProposalValue = TypeAliasType(
    "ProposalValue",
    str
    | int
    | float
    | bool
    | ContractModel
    | dict[str, "ProposalValue"]
    | tuple["ProposalValue", ...]
    | list["ProposalValue"]
    | None,
)


def align_facts(facts: tuple[Fact, ...], sources: tuple[SourceSnapshot, ...]) -> tuple[Fact, ...]:
    """Correct only a unique exact quote inside its already-declared current source."""
    by_id = {source.source_id: source for source in sources}
    aligned: list[Fact] = []
    for fact in facts:
        source = by_id.get(fact.source_id)
        if source is None or (
            fact.span.end <= len(source.text)
            and source.text[fact.span.start : fact.span.end] == fact.quote
        ):
            aligned.append(fact)
            continue
        start = source.text.find(fact.quote)
        require(
            bool(fact.quote) and start >= 0 and source.text.find(fact.quote, start + 1) < 0,
            "source_span",
            "Only a unique exact quote can establish corrected offsets",
        )
        aligned.append(
            fact.model_copy(update={"span": SourceSpan(start=start, end=start + len(fact.quote))})
        )
    return tuple(aligned)


def provisional_budget(value: ProposalValue) -> ProposalValue:
    """Permit SDK parsing of derived counts before authoritative request allocation."""
    if isinstance(value, ContractModel):
        return value
    fields = TypeAdapter(dict[str, ProposalValue]).validate_python(value)
    outline = fields.get("outline")
    if not isinstance(outline, dict):
        return value
    proposal = TypeAdapter(dict[str, ProposalValue]).validate_python(outline)
    budget = proposal.get("budget")
    if not isinstance(budget, dict):
        return value
    updated = TypeAdapter(dict[str, ProposalValue]).validate_python(budget)
    if not {"max_chars", "subtitle_reserved_chars", "usable_body_chars"}.issubset(updated):
        return value
    if updated.get("max_chars") is None:
        updated["subtitle_reserved_chars"] = None
        updated["usable_body_chars"] = None
    elif updated.get("subtitle_reserved_chars") is None:
        updated["subtitle_reserved_chars"] = 0
    return {**fields, "outline": {**proposal, "budget": updated}}


def title_reservation(role: str, policy: StrictLengthPolicy) -> int:
    """Use the existing fallback's role-derived phrase as a provisional reservation."""
    return max(1, count_characters("확인된 " + role, policy))


def reservation_reason(role: str) -> str:
    """Keep the same per-outline explanation for normal and fallback allocation."""
    return f"소제목 잠정 예약은 첫 설명 역할({role})의 짧은 요약 길이에 근거합니다."


def validate_candidate_relations(analysis: Analysis) -> None:
    """Require an explicit decision for each relation the model itself declares."""
    for candidate in analysis.answer_candidates:
        for requirement_id in candidate.requirement_ids:
            links = tuple(
                link
                for link in analysis.evidence_links
                if link.candidate_id == candidate.candidate_id
                and link.requirement_id == requirement_id
            )
            gaps = tuple(
                gap
                for gap in analysis.gaps
                if requirement_id in gap.requirement_ids
                and gap.candidate_id in (None, candidate.candidate_id)
            )
            require(
                bool(links or gaps),
                "candidate_evidence",
                "Declared candidate requirement needs an explicit evidence link or gap",
            )
            for link in links:
                require(
                    bool(link.reason.strip()),
                    "evidence_reason",
                    "Evidence relation needs its decision rationale",
                )
