"""Complete absent comparison rows without manufacturing semantic assessments."""

from .contracts import DraftBundle, IntegrationRequirementCheck, ReverseOutline
from .stage_integration_data import IntegrationPayload, IntegrationProposal
from .stage_integration_records import structural_reverse, unassessed_requirements


def complete_reverse(
    output: IntegrationProposal, bundle: DraftBundle
) -> tuple[ReverseOutline, ...]:
    """Retain supplied summaries and append unassessed rows for otherwise unreported paragraphs."""
    present = {row.paragraph_id for row in output.reverse_outline if row.scope == "candidate"}
    return (
        *output.reverse_outline,
        *(
            row
            for row in structural_reverse(bundle, "candidate")
            if row.paragraph_id not in present
        ),
    )


def complete_requirements(
    output: IntegrationProposal,
    payload: IntegrationPayload,
    bundle: DraftBundle,
) -> tuple[IntegrationRequirementCheck, ...]:
    """Represent missing requirement comparisons as unassessed with actual locations."""
    present = {row.requirement_id for row in output.requirement_checks}
    defaults = unassessed_requirements(
        payload.baseline_bundle, bundle, payload.analysis, payload.outline
    )
    return (
        *output.requirement_checks,
        *(row for row in defaults if row.requirement_id not in present),
    )
