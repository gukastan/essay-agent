"""Share writing eligibility across gap handling and structure planning."""

from .contracts import Analysis, EvidenceLink, Fact


def eligible_links(analysis: Analysis, facts: tuple[Fact, ...]) -> tuple[EvidenceLink, ...]:
    """Require applicable, nonexcluded links backed entirely by available current facts."""
    available = {fact.fact_id for fact in facts if fact.information_state == "available"}
    interpreted = {
        requirement.requirement_id
        for requirement in analysis.requirements
        if requirement.resolution != "unparsed"
    }
    return tuple(
        link
        for link in analysis.evidence_links
        if link.requirement_id in interpreted
        and link.information_state == "available"
        and link.use_status == "candidate"
        and link.applicability == "applies"
        and link.information_role != "exclude"
        and link.fact_ids
        and set(link.fact_ids) <= available
    )
