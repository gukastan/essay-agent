"""Public contract_rendering boundary contracts."""

from unicodedata import normalize

from .contract_drafts import DraftBundle
from .contract_sources import StrictLengthPolicy


def normalized_text(text: str) -> str:
    """Enforce normalized text boundary semantics."""
    return normalize("NFC", text.replace("\r\n", "\n").replace("\r", "\n"))


def count_characters(text: str, policy: StrictLengthPolicy) -> int:
    """Enforce count characters boundary semantics."""
    normalized = normalized_text(text)
    if not policy.include_newlines:
        normalized = normalized.replace("\n", "")
    if not policy.include_spaces:
        normalized = "".join(char for char in normalized if char == "\n" or not char.isspace())
    return len(normalized)


def render_body(bundle: DraftBundle) -> str:
    """Enforce render body boundary semantics."""
    return normalized_text(
        "\n\n".join(
            " ".join(sentence.text for sentence in paragraph.sentences)
            for paragraph in bundle.paragraphs
            if paragraph.sentences
        )
    )


def render_copy_text(bundle: DraftBundle) -> str:
    """Enforce render copy text boundary semantics."""
    body = render_body(bundle)
    if bundle.subtitle and bundle.subtitle_placement == "answer":
        return normalized_text(f"{bundle.subtitle}\n\n{body}")
    return body


def counted_text(bundle: DraftBundle, policy: StrictLengthPolicy) -> str:
    """Enforce counted text boundary semantics."""
    body = render_body(bundle)
    if policy.include_subtitle and bundle.subtitle and bundle.subtitle_placement == "answer":
        return normalized_text(f"{bundle.subtitle}\n\n{body}")
    return body
