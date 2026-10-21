"""Narrow parsing boundary for SDK result content, including malformed peers."""

from typing import Annotated, ClassVar, Literal

from pydantic import BaseModel, ConfigDict, Field

from .contract_base import ContractViolationError


class WireModel(BaseModel):
    """Accept SDK envelope extensions while validating consumed fields strictly."""

    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True, extra="ignore")


class TextBlock(WireModel):
    """Only textual content is admissible for these essay capabilities."""

    type: Literal["text"]
    text: str


class ToolPayload(WireModel):
    """Tool envelope fields consumed by the essay client."""

    is_error: bool
    content: Annotated[tuple[TextBlock, ...], Field(min_length=1)]

    def text(self) -> str:
        """Return JSON text assembled from all text blocks."""
        return "\n".join(block.text for block in self.content)


class ResourceBlock(WireModel):
    """Text resource contents, excluding blob-only responses."""

    text: str


class ResourcePayload(WireModel):
    """Resource envelope requiring at least one text block."""

    contents: Annotated[tuple[ResourceBlock, ...], Field(min_length=1)]

    def text(self) -> str:
        """Reject whitespace-only resources before local fallback."""
        text = "\n".join(block.text for block in self.contents)
        if not text.strip():
            msg = "resource_text"
            raise ContractViolationError(msg, "Resource response is empty")
        return text


class PromptMessage(WireModel):
    """A textual message in a prompt response."""

    content: TextBlock


class PromptPayload(WireModel):
    """Prompt envelope requiring nonempty textual messages."""

    messages: Annotated[tuple[PromptMessage, ...], Field(min_length=1)]

    def text(self) -> str:
        """Reject whitespace-only prompts before local fallback."""
        text = "\n".join(message.content.text for message in self.messages)
        if not text.strip():
            msg = "prompt_text"
            raise ContractViolationError(msg, "Prompt response is empty")
        return text
