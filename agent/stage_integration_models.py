"""Typed integration proposal validated inside the adapter attempt boundary."""

from typing import Self

from pydantic import model_validator

from .stage_analysis_models import PayloadValidationInfo
from .stage_integration_contract import validate_proposal
from .stage_integration_data import IntegrationPayload, IntegrationProposal

__all__ = ["IntegrationOutput", "IntegrationPayload"]


class IntegrationOutput(IntegrationProposal):
    """Check complete parsed edit proposals against current baseline and source evidence."""

    @model_validator(mode="after")
    def current_payload(self, info: PayloadValidationInfo) -> Self:
        """Check complete parsed proposals within the provider retry budget."""
        if info.context is not None:
            payload = IntegrationPayload.model_validate(info.context["payload"])
            validate_proposal(payload, self)
        return self
