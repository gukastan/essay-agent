"""Public contract_validation boundary contracts."""

from .contract_composition_validation import validate_composition
from .contract_context import ContractContext
from .contract_integration_validation import validate_integration
from .contract_measurement import validate_measurements
from .contract_outline_validation import validate_outline
from .contract_references import validate_analysis, validate_sources
from .contract_result_validation import validate_result
from .contract_review_validation import validate_review


def validate_contract(context: ContractContext) -> None:
    """Enforce validate contract boundary semantics."""
    validate_sources(context)
    validate_analysis(context)
    validate_outline(context)
    validate_composition(context)
    validate_integration(context)
    validate_review(context)
    validate_result(context)
    validate_measurements(context)
