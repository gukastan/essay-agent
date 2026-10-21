"""Produce immutable writing-stage lineage, actual sentence checks and length."""

from .composition_rules import (
    assembled_paragraphs,
    general_fallback,
    length_snapshot,
    new_version,
    personalization_for,
)
from .contracts import (
    DraftBundle,
    DraftParagraph,
    ParagraphId,
    SectionCheck,
    SentenceId,
    WritingNote,
    WritingReport,
)
from .stage_writing_cleanup import cleanup_writing
from .stage_writing_models import WritingOutput, WritingPayload


def finish_writing(
    output: WritingOutput,
    payload: WritingPayload,
    original_sentence_ids: tuple[SentenceId, ...] = (),
) -> tuple[WritingOutput, WritingReport]:
    """Keep every planned section and recalculate references after safety cleanup."""
    clean = cleanup_writing(output, payload, original_sentence_ids)
    paragraphs = assembled_paragraphs(clean.section_drafts, payload.outline)
    fallback = () if paragraphs else general_fallback()
    if fallback:
        paragraphs = (DraftParagraph(paragraph_id=ParagraphId("fallback"), sentences=fallback),)
    personalization = personalization_for(
        paragraphs, payload.facts, payload.analysis, payload.outline
    )
    bundle = DraftBundle(
        version_id=new_version(),
        evidence_version=payload.evidence_version,
        paragraphs=paragraphs,
        subtitle=None,
        subtitle_fact_ids=(),
        subtitle_placement="answer",
        personalization=personalization,
    )
    checks: list[SectionCheck] = []
    notes = list(clean.notes)
    sections = {section.section_id: section for section in payload.outline.sections}
    for draft in clean.section_drafts:
        section = sections[draft.section_id]
        ids = tuple(
            s.sentence_id
            for part in clean.section_drafts
            for allocation in part.allocations
            for s in allocation.sentences
            if section.section_id in s.section_ids
        )
        checks.append(
            SectionCheck(
                section_id=section.section_id,
                state="not_written"
                if not ids
                else "general"
                if section.write_mode == "general"
                else "partial"
                if section.gap_ids
                else "drafted",
                sentence_ids=ids,
                requirement_ids=section.requirement_ids,
                gap_ids=section.gap_ids,
                reason="현재 남은 문장과 원문 배정에 따른 잠정 작성 상태입니다.",
            )
        )
        if not ids:
            notes.append(
                WritingNote(
                    code="contract_mismatch" if section.fact_ids else "missing_information",
                    section_ids=(section.section_id,),
                    requirement_ids=section.requirement_ids,
                    sentence_ids=(),
                    gap_ids=section.gap_ids,
                    handling="retained_for_review" if section.fact_ids else "omitted",
                    message=(
                        "제공된 근거가 있으나 작성된 문장이 없어 표현 보완이 필요합니다."
                        if section.fact_ids
                        else "미확인 개인 내용을 채우지 않고 이 부분을 남겨 두었습니다."
                    ),
                    proposed_question=None,
                )
            )
    report = WritingReport(
        draft_id=bundle.version_id,
        evidence_version=payload.evidence_version,
        personalization=personalization,
        notes=tuple(notes),
        section_checks=tuple(checks),
        length_snapshot=length_snapshot(bundle, payload.request.length_policy),
        fallback_sentences=fallback,
    )
    return clean, report
