"""Preserve valid parsed allocations and remove reported unsupported prose."""

from .contract_base import ContractViolationError
from .contracts import DraftAllocation, SectionDraft, Sentence, SentenceId, WritingNote
from .stage_writing_models import WritingOutput, WritingPayload, WritingRecovery, writing_context
from .stage_writing_validation import validate_allocation_sentence


def cleanup_writing(
    output: WritingOutput,
    payload: WritingPayload,
    original_sentence_ids: tuple[SentenceId, ...] = (),
) -> WritingOutput:
    """Filter each complete parsed sentence against current facts and reported problems."""
    context = writing_context(payload)
    sections = {section.section_id: section for section in payload.outline.sections}
    original_ids = {
        sentence.sentence_id
        for draft in output.section_drafts
        for allocation in draft.allocations
        for sentence in allocation.sentences
    }
    original_ids.update(original_sentence_ids)
    requirements = {r.requirement_id for r in payload.analysis.requirements}
    gaps = {gap.gap_id for gap in payload.analysis.gaps}
    notes = [
        note
        for note in output.notes
        if set(note.section_ids) <= set(sections)
        and set(note.requirement_ids) <= requirements
        and set(note.gap_ids) <= gaps
        and set(note.sentence_ids) <= original_ids
    ]
    rejected = {
        sid
        for note in notes
        if note.code in ("unsupported_claim", "conflict", "contract_mismatch")
        for sid in note.sentence_ids
    }
    seen: set[SentenceId] = set()
    parts: list[SectionDraft] = []
    for section in payload.outline.sections:
        allocations: list[DraftAllocation] = []
        for draft in output.section_drafts:
            if draft.section_id != section.section_id or section.write_mode == "omit":
                continue
            for allocation in draft.allocations:
                valid: list[Sentence] = []
                for sentence in allocation.sentences:
                    try:
                        validate_allocation_sentence(
                            sentence, draft, allocation.planned_paragraph_id, context
                        )
                    except ContractViolationError:
                        notes.append(
                            WritingNote(
                                code="contract_mismatch",
                                section_ids=(section.section_id,),
                                requirement_ids=section.requirement_ids,
                                sentence_ids=(sentence.sentence_id,),
                                gap_ids=section.gap_ids,
                                handling="omitted",
                                message="현재 배정 범위를 벗어난 문장을 제외했습니다.",
                                proposed_question=None,
                            )
                        )
                        continue
                    if sentence.sentence_id not in rejected and sentence.sentence_id not in seen:
                        valid.append(sentence)
                        seen.add(sentence.sentence_id)
                if valid:
                    allocations.append(allocation.model_copy(update={"sentences": tuple(valid)}))
        parts.append(SectionDraft(section_id=section.section_id, allocations=tuple(allocations)))
    valid_notes = tuple(note for note in notes if set(note.section_ids) <= set(sections))
    return output.model_copy(update={"section_drafts": tuple(parts), "notes": valid_notes})


def merge_partial(
    previous: WritingRecovery | None, current: WritingOutput, payload: WritingPayload
) -> WritingRecovery:
    """Carry original proposal identities beside retained partial prose for diagnostic history."""
    history = tuple(
        dict.fromkeys(
            (
                *(previous.original_sentence_ids if previous else ()),
                *(
                    s.sentence_id
                    for d in current.section_drafts
                    for a in d.allocations
                    for s in a.sentences
                ),
            )
        )
    )
    current = isolate_retry_identity(previous, current)
    clean = cleanup_writing(current, payload)
    if previous is not None:
        clean = cleanup_writing(
            clean.model_copy(
                update={
                    "section_drafts": (*previous.section_drafts, *clean.section_drafts),
                    "notes": (*previous.notes, *clean.notes),
                }
            ),
            payload,
            history,
        )
    return WritingRecovery(
        section_drafts=clean.section_drafts,
        notes=clean.notes,
        section_checks=clean.section_checks,
        personalization=clean.personalization,
        original_sentence_ids=history,
    )


def isolate_retry_identity(
    previous: WritingRecovery | None, current: WritingOutput
) -> WritingOutput:
    """Prevent reused IDs with different content from condemning prior valid sentences."""
    if previous is None:
        return current
    prior = {
        s.sentence_id: s
        for d in previous.section_drafts
        for a in d.allocations
        for s in a.sentences
    }
    collisions = {
        s.sentence_id
        for d in current.section_drafts
        for a in d.allocations
        for s in a.sentences
        if s.sentence_id in prior and s != prior[s.sentence_id]
    }
    drafts = tuple(
        d.model_copy(
            update={
                "allocations": tuple(
                    a.model_copy(
                        update={
                            "sentences": tuple(
                                s for s in a.sentences if s.sentence_id not in collisions
                            )
                        }
                    )
                    for a in d.allocations
                )
            }
        )
        for d in current.section_drafts
    )
    notes = tuple(
        note.model_copy(
            update={
                "sentence_ids": tuple(sid for sid in note.sentence_ids if sid not in collisions)
            }
        )
        for note in current.notes
        if not note.sentence_ids or set(note.sentence_ids) - collisions
    )
    return current.model_copy(update={"section_drafts": drafts, "notes": notes})
