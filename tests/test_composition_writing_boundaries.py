import pytest

from agent import contracts as c
from agent.stage_writing_models import WritingOutput, WritingPayload
from agent.stage_writing_report import finish_writing
from tests.composition_adversarial_support import prepared_context


def current() -> tuple[WritingPayload, WritingOutput]:
    ctx = prepared_context()
    assert ctx.request is not None
    assert ctx.analysis is not None
    assert ctx.outline is not None
    return WritingPayload(
        request=ctx.request,
        evidence_version=ctx.evidence_version,
        sources=ctx.sources,
        facts=ctx.facts,
        analysis=ctx.analysis,
        outline=ctx.outline,
    ), WritingOutput(
        section_drafts=ctx.section_drafts, notes=(), section_checks=(), personalization="partial"
    )


@pytest.mark.parametrize("field", ["requirement_ids", "gap_ids", "sentence_ids"])
def test_unknown_note_references_are_discarded(field: str) -> None:
    # Given a parsed note whose section is valid but another reference is foreign.
    payload, output = current()
    note = c.WritingNote(
        code="conflict",
        section_ids=(output.section_drafts[0].section_id,),
        requirement_ids=(),
        gap_ids=(),
        sentence_ids=(),
        handling="omitted",
        message="Finding",
        proposed_question=None,
    )
    note = note.model_copy(update={field: ("foreign",)})
    # When current proposal references are normalized.
    _, report = finish_writing(output.model_copy(update={"notes": (note,)}), payload)
    # Then no foreign diagnostic becomes current evidence.
    assert note not in report.notes


def test_available_content_omission_is_not_missing_user_information() -> None:
    # Given a grounded section with supplied facts but no generated sentence.
    payload, output = current()
    section = next(s for s in payload.outline.sections if s.fact_ids and s.write_mode != "omit")
    output = output.model_copy(
        update={
            "section_drafts": tuple(
                d for d in output.section_drafts if d.section_id != section.section_id
            )
        }
    )
    # When writing normalizes the missing section.
    _, report = finish_writing(output, payload)
    # Then the repairable model omission is distinguished from an information gap.
    notes = [n for n in report.notes if section.section_id in n.section_ids]
    assert any(n.code == "contract_mismatch" and n.handling == "retained_for_review" for n in notes)
    assert not any(n.code == "missing_information" for n in notes)


def test_removed_unsafe_sentence_reference_remains_historical() -> None:
    # Given a valid current sentence with a semantic unsupported-content finding.
    payload, output = current()
    sentence = output.section_drafts[0].allocations[0].sentences[0]
    note = c.WritingNote(
        code="unsupported_claim",
        section_ids=sentence.section_ids,
        requirement_ids=(),
        gap_ids=(),
        sentence_ids=(sentence.sentence_id,),
        handling="omitted",
        message="Finding",
        proposed_question=None,
    )
    # When that sentence is excluded.
    clean, report = finish_writing(output.model_copy(update={"notes": (note,)}), payload)
    # Then current sentence checks drop it while the safety report preserves its history.
    assert note in report.notes
    assert sentence.sentence_id not in {
        s.sentence_id for d in clean.section_drafts for a in d.allocations for s in a.sentences
    }
    assert all(sentence.sentence_id not in check.sentence_ids for check in report.section_checks)
