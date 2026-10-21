from pathlib import Path
from typing import Final

import anyio
import pytest

from agent import contracts as c
from agent import graph
from agent.deps import SupervisorDeps
from agent.fake_llm import FastLLM, QualityLLM
from agent.stage_integration_models import IntegrationOutput, IntegrationPayload
from tests.composition_adversarial_support import (
    LEARNING,
    Scenario,
    ScriptedIntegration,
    prepared_context,
)

BASELINE_TEXT: Final = (
    "I sorted library books. I watered the garden.\n\nMy task was sorting books. " + LEARNING
)


class Receipt(c.ContractModel):
    context: c.ContractContext
    model_payload: IntegrationPayload
    proposal: IntegrationOutput
    selected: c.DraftBundle
    report: c.IntegrationReport
    calls: tuple[str, ...]


async def execute(scenario: Scenario) -> Receipt:
    context = prepared_context()
    assert context.request is not None
    assert context.analysis is not None
    assert context.outline is not None
    assert context.writing_report is not None
    script = ScriptedIntegration(scenario)
    fast, quality = FastLLM(script), QualityLLM(script)
    state = graph.EssayState(
        request=context.request,
        evidence_version=context.evidence_version,
        revision_context=c.RevisionContext(source_history=(), question_registry=()),
        sources=context.sources,
        facts=context.facts,
        analysis=context.analysis,
        outline=context.outline,
        section_drafts=context.section_drafts,
        writing_report=context.writing_report,
    )
    snapshot = context.model_dump_json()
    try:
        update = await graph.integrate_draft(state, SupervisorDeps(fast, quality))
    finally:
        await fast.aclose()
        await quality.aclose()
    assert context.model_dump_json() == snapshot
    assert "candidate_bundle" in update
    assert "integration_report" in update
    selected, report = update["candidate_bundle"], update["integration_report"]
    c.validate_contract(
        context.model_copy(update={"bundle": selected, "integration_report": report})
    )
    return Receipt(
        context=context,
        model_payload=script.payloads[0],
        proposal=script.proposals[0],
        selected=selected,
        report=report,
        calls=tuple(script.calls),
    )


def run_case(scenario: Scenario, directory: Path) -> Receipt:
    receipt = anyio.run(execute, scenario)
    _ = (directory / (scenario + ".json")).write_text(receipt.model_dump_json(indent=2))
    assert receipt.calls == ("integrate_draft",)
    assert receipt.report.baseline_bundle == receipt.model_payload.baseline_bundle
    assert receipt.report.candidate_version_id == receipt.selected.version_id
    assert receipt.selected.evidence_version == receipt.context.evidence_version
    return receipt


def assert_rollback_is_current(receipt: Receipt) -> None:
    current_ids = {s.sentence_id for p in receipt.selected.paragraphs for s in p.sentences}
    baseline_ids = {
        s.sentence_id for p in receipt.report.baseline_bundle.paragraphs for s in p.sentences
    }
    assert receipt.report.reverse_outline
    assert {
        sid
        for row in receipt.report.reverse_outline
        if row.scope == "candidate"
        for sid in row.sentence_ids
    } == current_ids
    for row in receipt.report.reverse_outline:
        assert row.semantic_status == "unassessed"
        assert row.gist is None
        assert row.roles == ()
        assert row.requirement_ids == ()
        assert row.difference_from_plan is None
        assert (
            set(row.sentence_ids) <= {"baseline": baseline_ids, "candidate": current_ids}[row.scope]
        )
    assert all(check.after_state == "unassessed" for check in receipt.report.requirement_checks)
    assert {sid for edit in receipt.report.edits for sid in edit.after_sentence_ids} == current_ids


def test_control_keeps_supported_learning_and_candidate_assessment(tmp_path: Path) -> None:
    # Given a current-source draft with a sole grounded learning statement and no reported loss.
    scenario: Scenario = "control"
    # When one schema-valid integration proposal is processed.
    receipt = run_case(scenario, tmp_path)
    # Then the intact baseline content and assessed candidate report survive.
    assert c.render_body(receipt.selected) == BASELINE_TEXT
    assert receipt.report.length_after.body_chars == 121
    assert receipt.report.requirement_checks[0].after_state == "expressed"
    assert all(row.semantic_status == "assessed" for row in receipt.report.reverse_outline)


def test_lost_sole_grounded_learning_restores_valid_baseline(tmp_path: Path) -> None:
    # Given a valid proposal that reports loss of the only required learning answer.
    scenario: Scenario = "loss"
    # When the integration node applies that reported comparison.
    receipt = run_case(scenario, tmp_path)
    # Then it restores the original evidence-backed answer and invalidates candidate semantics.
    assert all(
        s.sentence_id != "sentence-learning"
        for p in receipt.proposal.paragraphs
        for s in p.sentences
    )
    assert receipt.report.selection == "baseline"
    assert c.render_body(receipt.selected) == BASELINE_TEXT
    assert receipt.report.length_after.body_chars == 121
    assert_rollback_is_current(receipt)


def test_unsupported_baseline_learning_is_never_restored(tmp_path: Path) -> None:
    # Given the same omitted learning, now explicitly reported unsupported in the baseline.
    scenario: Scenario = "unsupported_baseline"
    # When rollback processes both requirement loss and the baseline issue.
    receipt = run_case(scenario, tmp_path)
    # Then history keeps the original while the selected copy excludes the flagged assertion.
    baseline_ids = {
        s.sentence_id for p in receipt.report.baseline_bundle.paragraphs for s in p.sentences
    }
    assert "sentence-learning" in baseline_ids
    assert c.render_body(receipt.selected) == (
        "I sorted library books. I watered the garden.\n\nMy task was sorting books."
    )
    assert receipt.report.length_after.body_chars == 73
    assert receipt.report.selection == "edited"
    assert any(
        e.operation == "delete" and e.before_sentence_ids == ("sentence-learning",)
        for e in receipt.report.edits
    )
    assert_rollback_is_current(receipt)


@pytest.mark.parametrize("scenario", ["metric", "causality"])
def test_reported_new_metric_or_causality_rejects_candidate(
    scenario: Scenario,
    tmp_path: Path,
) -> None:
    # Given a schema-valid rewrite using known IDs but a reported invented metric or cause.
    expected_code = "unsupported_" + scenario
    # When the single integration proposal is considered.
    receipt = run_case(scenario, tmp_path)
    # Then the original answer returns and rejected sentence IDs stay outside current issues.
    assert receipt.report.selection == "baseline"
    assert c.render_body(receipt.selected) == BASELINE_TEXT
    assert receipt.report.length_after.body_chars == 121
    matching = [issue for issue in receipt.report.issues if issue.code == expected_code]
    assert matching
    assert all(issue.scope == "rejected_candidate" for issue in matching)
    assert all(
        "sentence-injected" not in issue.sentence_ids
        for issue in receipt.report.issues
        if issue.scope == "current"
    )
    assert_rollback_is_current(receipt)


def test_multi_event_merge_and_move_preserve_attribution_and_complete_trace(tmp_path: Path) -> None:
    # Given two separate events and a valid merge that explicitly preserves their attribution.
    scenario: Scenario = "merge_move"
    # When the candidate moves a paragraph and merges its other two sentences.
    receipt = run_case(scenario, tmp_path)
    # Then current text, event-bound facts, section ownership and every edit endpoint agree.
    assert receipt.report.selection == "edited"
    assert c.render_body(receipt.selected) == (
        "My task was sorting books. "
        + LEARNING
        + "\n\n"
        + "At the library I sorted books; separately, I watered the garden."
    )
    merged = receipt.selected.paragraphs[1].sentences[0]
    assert merged.sentence_id == "sentence-merged"
    assert merged.section_ids == ("section-action", "section-explanation")
    assert merged.fact_ids == ("fact-library", "fact-garden")
    assert {
        fact.fact_id: fact.experience_id
        for fact in receipt.context.facts
        if fact.fact_id in merged.fact_ids
    } == {
        "fact-library": "event-library",
        "fact-garden": "event-garden",
    }
    assert [
        (edit.operation, edit.before_sentence_ids, edit.after_sentence_ids)
        for edit in receipt.report.edits
    ] == [
        ("merge", ("sentence-one", "sentence-two"), ("sentence-merged",)),
        ("move", ("sentence-three",), ("sentence-three",)),
        ("move", ("sentence-learning",), ("sentence-learning",)),
    ]
    assert (
        receipt.selected.paragraphs[0].sentences
        == receipt.report.baseline_bundle.paragraphs[1].sentences
    )
    assert all(row.semantic_status == "assessed" for row in receipt.report.reverse_outline)


def test_all_personal_claims_removed_still_delivers_general_prose(tmp_path: Path) -> None:
    # Given a complete proposal with every baseline personal claim explicitly reported unsupported.
    scenario: Scenario = "unsupported_all"
    # When the same integration boundary removes all flagged claims.
    receipt = run_case(scenario, tmp_path)
    # Then a nonempty general draft replaces them with complete deletion/addition provenance.
    assert receipt.report.selection == "general_fallback"
    assert receipt.selected.personalization == "non_personalized"
    sentences = tuple(s for p in receipt.selected.paragraphs for s in p.sentences)
    assert sentences
    assert all(s.claim_kind == "general_statement" and s.text.strip() for s in sentences)
    assert all(not s.section_ids and not s.fact_ids for s in sentences)
    baseline_ids = {
        s.sentence_id for p in receipt.report.baseline_bundle.paragraphs for s in p.sentences
    }
    assert not baseline_ids.intersection(s.sentence_id for s in sentences)
    assert receipt.report.length_after.body_chars > 0
    assert {
        sid
        for edit in receipt.report.edits
        if edit.operation == "delete"
        for sid in edit.before_sentence_ids
    } == baseline_ids
    assert any(edit.operation == "add_fallback" for edit in receipt.report.edits)
    assert_rollback_is_current(receipt)
