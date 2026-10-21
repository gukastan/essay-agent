"""Deterministic readable fallback, paragraph assembly and body-only measurement."""

from uuid import uuid4

from .contract_base import Personalization
from .contracts import (
    Analysis,
    DraftBundle,
    DraftParagraph,
    Fact,
    LengthSnapshot,
    Outline,
    ParagraphId,
    SectionDraft,
    Sentence,
    SentenceId,
    StrictLengthPolicy,
    VersionId,
    count_characters,
    render_body,
)


def new_version() -> VersionId:
    """Create server-owned identity for an immutable draft snapshot."""
    return VersionId(str(uuid4()))


def general_fallback() -> tuple[Sentence, ...]:
    """Provide complete prose without assigning personal experience or beliefs."""
    return (
        Sentence(
            sentence_id=SentenceId(f"fallback-{uuid4()}"),
            text=(
                "일의 과정에는 상황의 제약과 여러 선택이 함께 존재합니다. "
                "선택한 행동과 확인된 결과를 구분하는 관점은 "
                "그 과정의 의미를 이해하는 데 도움이 됩니다."
            ),
            section_ids=(),
            fact_ids=(),
            claim_kind="general_statement",
        ),
    )


def assembled_paragraphs(
    drafts: tuple[SectionDraft, ...],
    outline: Outline,
) -> tuple[DraftParagraph, ...]:
    """Render each owned sentence once in planned paragraph/allocation order."""
    parts = {draft.section_id: draft for draft in drafts}
    seen: set[SentenceId] = set()
    paragraphs: list[DraftParagraph] = []
    for plan in sorted(outline.paragraphs, key=lambda item: item.order):
        sentences: list[Sentence] = []
        for allocation in plan.allocations:
            draft = parts.get(allocation.section_id)
            if draft is None:
                continue
            for written in draft.allocations:
                if written.planned_paragraph_id != plan.paragraph_id:
                    continue
                for sentence in written.sentences:
                    if sentence.sentence_id not in seen:
                        seen.add(sentence.sentence_id)
                        sentences.append(sentence)
        if sentences:
            paragraphs.append(
                DraftParagraph(
                    paragraph_id=ParagraphId(f"actual:{plan.paragraph_id}"),
                    sentences=tuple(sentences),
                )
            )
    return tuple(paragraphs)


def personalization_for(
    paragraphs: tuple[DraftParagraph, ...],
    facts: tuple[Fact, ...],
    analysis: Analysis,
    outline: Outline,
) -> Personalization:
    """Recompute whether retained prose contains actual applicant-grounded claims."""
    applicant = {fact.fact_id for fact in facts if fact.source_kind == "applicant"}
    personal = tuple(
        sentence
        for paragraph in paragraphs
        for sentence in paragraph.sentences
        if sentence.claim_kind in ("personal_event", "stated_view", "interpretation")
        and applicant.intersection(sentence.fact_ids)
    )
    if not personal:
        return "non_personalized"
    sections = {sid for sentence in personal for sid in sentence.section_ids}
    required = {
        r.requirement_id
        for r in analysis.requirements
        if r.required_by_prompt or r.information_role == "logical_core"
    }
    mapped = {
        rid
        for section in outline.sections
        if section.section_id in sections
        for rid in section.requirement_ids
    }
    return "grounded_in_user_input" if required <= mapped and not analysis.gaps else "partial"


def length_snapshot(bundle: DraftBundle, policy: StrictLengthPolicy) -> LengthSnapshot:
    """Measure actual NFC body text; never substitute subtitle reservation for title length."""
    size = count_characters(render_body(bundle), policy)
    return LengthSnapshot(
        body_chars=size,
        max_chars=policy.max_chars,
        include_spaces=policy.include_spaces,
        include_newlines=policy.include_newlines,
        include_subtitle=policy.include_subtitle,
        subtitle_pending=policy.include_subtitle,
        measurement_scope="body_only",
        body_limit_status="unspecified"
        if policy.max_chars is None
        else "over"
        if size > policy.max_chars
        else "within",
    )
