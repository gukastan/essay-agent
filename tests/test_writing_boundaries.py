from pathlib import Path

import anyio
import pytest

from agent import contracts as c
from agent import graph
from agent.deps import SupervisorDeps
from agent.fake_llm import FastLLM, QualityLLM
from agent.stage_writing_models import WritingOutput, WritingPayload
from tests.writing_boundary_support import Scenario, ScriptedWriting, context_for


class WritingReceipt(c.ContractModel):
    context: c.ContractContext
    payloads: tuple[WritingPayload, ...]
    proposals: tuple[WritingOutput, ...]
    drafts: tuple[c.SectionDraft, ...]
    report: c.WritingReport
    technical_issues: tuple[c.TechnicalIssue, ...]
    calls: tuple[str, ...]


async def execute(scenario: Scenario) -> WritingReceipt:
    context = context_for(scenario)
    assert context.request is not None
    assert context.analysis is not None
    assert context.outline is not None
    script = ScriptedWriting(scenario, context)
    fast, quality = FastLLM(script), QualityLLM(script)
    before = context.model_dump_json()
    try:
        update = await graph.write_sections(
            graph.EssayState(
                request=context.request,
                evidence_version=context.evidence_version,
                revision_context=c.RevisionContext(source_history=(), question_registry=()),
                sources=context.sources,
                facts=context.facts,
                analysis=context.analysis,
                outline=context.outline,
            ),
            SupervisorDeps(fast, quality),
        )
    finally:
        await fast.aclose()
        await quality.aclose()
    assert context.model_dump_json() == before
    assert "section_drafts" in update
    assert "writing_report" in update
    c.validate_contract(
        context.model_copy(
            update={
                "section_drafts": update["section_drafts"],
                "writing_report": update["writing_report"],
            }
        )
    )
    return WritingReceipt(
        context=context,
        payloads=tuple(script.payloads),
        proposals=tuple(script.outputs),
        drafts=update["section_drafts"],
        report=update["writing_report"],
        technical_issues=update.get("technical_issues", ()),
        calls=tuple(script.calls),
    )


def run_case(scenario: Scenario, directory: Path, attempts: int = 1) -> WritingReceipt:
    receipt = anyio.run(execute, scenario)
    _ = (directory / (scenario + ".json")).write_text(receipt.model_dump_json(indent=2))
    assert receipt.calls == ("write_sections",) * attempts
    assert all(p.evidence_version == receipt.context.evidence_version for p in receipt.payloads)
    return receipt


def sentences(receipt: WritingReceipt) -> tuple[c.Sentence, ...]:
    return tuple(s for d in receipt.drafts for a in d.allocations for s in a.sentences)


def test_valid_parsed_parts_survive_invalid_sibling_then_timeout(tmp_path: Path) -> None:
    # Given one parsed response with a valid library/learning and foreign garden reference.
    scenario: Scenario = "partial_timeout"
    # When the second and final attempt times out through the actual adapter retry owner.
    receipt = run_case(scenario, tmp_path, attempts=2)
    # Then only independently grounded original sentences survive without fabrication.
    assert len(receipt.proposals) == 1
    assert [(issue.code, issue.attempts) for issue in receipt.technical_issues] == [("timeout", 2)]
    assert {s.sentence_id: s.text for s in sentences(receipt)} == {
        "sentence-one": "I sorted library books.",
        "sentence-three": "My task was sorting books.",
        "sentence-learning": "I learned to agree on a method before starting.",
    }
    assert receipt.report.fallback_sentences == ()
    assert receipt.report.personalization != "non_personalized"
    assert any(
        note.code == "contract_mismatch" and note.sentence_ids == ("sentence-two",)
        for note in receipt.report.notes
    )


@pytest.mark.parametrize(("scenario", "attempts"), [("all_invalid", 2), ("all_removed", 1)])
def test_no_remaining_personal_claim_still_delivers_general_prose(
    scenario: Scenario,
    attempts: int,
    tmp_path: Path,
) -> None:
    # Given either invalid references everywhere or explicit unsupported findings for every claim.
    # When the writing stage exhausts technical recovery or applies semantic cleanup.
    receipt = run_case(scenario, tmp_path, attempts)
    # Then readable general prose remains, with no invented personal fact or allocation.
    assert not sentences(receipt)
    assert receipt.report.personalization == "non_personalized"
    assert receipt.report.fallback_sentences
    assert all(
        s.text.strip()
        and s.claim_kind == "general_statement"
        and not s.fact_ids
        and not s.section_ids
        for s in receipt.report.fallback_sentences
    )
    assert receipt.report.length_snapshot.body_chars > 0


@pytest.mark.parametrize("scenario", ["omitted", "missing"])
def test_available_omission_is_distinct_from_missing_learning(
    scenario: Scenario, tmp_path: Path
) -> None:
    # Given either supplied learning evidence or an explicit missing-learning gap and omit section.
    # When writing returns no learning sentence in either case.
    receipt = run_case(scenario, tmp_path)
    # Then only the genuinely absent information is classified as missing_information.
    notes = [n for n in receipt.report.notes if "section-result" in n.section_ids]
    expected = {"omitted": "contract_mismatch", "missing": "missing_information"}[scenario]
    assert any(n.code == expected for n in notes)
    if scenario == "omitted":
        assert not any(n.code == "missing_information" for n in notes)
    else:
        assert receipt.context.outline is not None
        assert receipt.context.outline.sections[2].write_mode == "omit"
        assert any(n.gap_ids == ("gap-result",) for n in notes)
    assert all("section-result" not in s.section_ids for s in sentences(receipt))
    assert sentences(receipt)


@pytest.mark.parametrize("scenario", ["bad_section", "bad_requirement", "bad_gap", "bad_sentence"])
def test_foreign_note_references_cannot_leak_or_remove_valid_claims(
    scenario: Scenario, tmp_path: Path
) -> None:
    # Given a note with one foreign reference and an otherwise valid target sentence.
    # When writing normalizes that parsed semantic note.
    receipt = run_case(scenario, tmp_path)
    # Then the invalid note cannot remove provided prose or enter the report.
    assert {s.sentence_id for s in sentences(receipt)} == {
        "sentence-one",
        "sentence-two",
        "sentence-three",
        "sentence-learning",
    }
    assert all(
        "foreign" not in (*n.section_ids, *n.requirement_ids, *n.gap_ids, *n.sentence_ids)
        for n in receipt.report.notes
    )


def test_valid_unsupported_note_removes_only_its_target(tmp_path: Path) -> None:
    # Given a valid unsupported note attached only to sentence-one.
    # When writing applies the explicit semantic finding.
    receipt = run_case("targeted", tmp_path)
    # Then other supplied facts and sentences remain while history keeps the removed target.
    assert {s.sentence_id for s in sentences(receipt)} == {
        "sentence-two",
        "sentence-three",
        "sentence-learning",
    }
    assert any(
        n.code == "unsupported_claim" and n.sentence_ids == ("sentence-one",)
        for n in receipt.report.notes
    )
    assert all("sentence-one" not in check.sentence_ids for check in receipt.report.section_checks)


def test_merged_sentence_has_one_owner_and_complete_section_fact_mapping(tmp_path: Path) -> None:
    # Given one explicit library/garden merge mapped to both same-paragraph allocations.
    # When writing validates and assembles its logical section outputs.
    receipt = run_case("merged", tmp_path)
    # Then the merged sentence has one owner while both sections reference its complete provenance.
    merged = [s for s in sentences(receipt) if s.sentence_id == "writing-merged"]
    assert len(merged) == 1
    assert merged[0].section_ids == ("section-action", "section-explanation")
    assert merged[0].fact_ids == ("fact-library", "fact-garden")
    assert [
        d.section_id
        for d in receipt.drafts
        for a in d.allocations
        if any(s.sentence_id == "writing-merged" for s in a.sentences)
    ] == ["section-action"]
    assert all(
        "writing-merged" in check.sentence_ids
        for check in receipt.report.section_checks
        if check.section_id in ("section-action", "section-explanation")
    )


def test_merged_sentence_cannot_borrow_another_owners_fact_permission(tmp_path: Path) -> None:
    # Given the same merge but its owning allocation permits only the library fact.
    # When both technical attempts violate that ownership boundary.
    receipt = run_case("merged_wrong_owner", tmp_path, attempts=2)
    # Then valid remaining prose survives while the unauthorized merge is excluded.
    assert {s.sentence_id for s in sentences(receipt)} == {"sentence-three", "sentence-learning"}
    assert receipt.report.fallback_sentences == ()
    assert any(
        n.code == "contract_mismatch" and "writing-merged" in n.sentence_ids
        for n in receipt.report.notes
    )


def test_later_unsafe_id_reuse_cannot_erase_prior_valid_prose(tmp_path: Path) -> None:
    # Given valid prose retained from attempt one and unsafe different prose reusing its ID in two.
    # When both parsed attempts fail another reference and the second reports its own prose unsafe.
    receipt = run_case("retry_collision", tmp_path, attempts=2)
    # Then earlier valid text survives and later unsupported text stays outside the draft.
    assert len(receipt.proposals) == 2
    assert {s.sentence_id: s.text for s in sentences(receipt)} == {
        "sentence-one": "I sorted library books.",
        "sentence-three": "My task was sorting books.",
        "sentence-learning": "I learned to agree on a method before starting.",
    }
    assert receipt.proposals[0].section_drafts[0].allocations[0].sentences[0].text != (
        receipt.proposals[1].section_drafts[0].allocations[0].sentences[0].text
    )


def test_retry_note_cannot_target_sentence_absent_from_its_own_proposal(tmp_path: Path) -> None:
    # Given a later retry note targeting a prior-only ID absent from its own parsed proposal.
    # When that retry fails a separate reference and stage recovery merges valid earlier content.
    receipt = run_case("retry_prior_only", tmp_path, attempts=2)
    # Then the foreign retry note cannot erase the prior validated sentence.
    assert "sentence-one" not in {
        s.sentence_id
        for d in receipt.proposals[1].section_drafts
        for a in d.allocations
        for s in a.sentences
    }
    assert {s.sentence_id: s.text for s in sentences(receipt)} == {
        "sentence-one": "I sorted library books.",
        "sentence-three": "My task was sorting books.",
        "sentence-learning": "I learned to agree on a method before starting.",
    }
