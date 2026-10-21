"""Provider wrappers validate only current payload references and repair scope."""

from typing import Self

from pydantic import model_validator

from .review_validation import validate_repair_output, validate_review_output
from .stage_analysis_models import PayloadValidationInfo
from .stage_review_data import RepairPayload, RepairProposal, ReviewJudgments, ReviewPayload

__all__ = ["RepairOutput", "RepairPayload", "ReviewOutput", "ReviewPayload"]


class ReviewOutput(ReviewJudgments):
    """Bind complete parsed judgments to the current source snapshot."""

    @model_validator(mode="after")
    def current_payload(self, info: PayloadValidationInfo) -> Self:
        """Validate current body references inside the shared retry budget."""
        if info.context is not None:
            validate_review_output(self, ReviewPayload.model_validate(info.context["payload"]))
        return self


class RepairOutput(RepairProposal):
    """Bind a complete parsed repair to current authorized targets."""

    @model_validator(mode="after")
    def current_payload(self, info: PayloadValidationInfo) -> Self:
        """Validate targeted edit ownership inside the shared retry budget."""
        if info.context is not None:
            validate_repair_output(self, RepairPayload.model_validate(info.context["payload"]))
        return self
