import pytest

from agent import contracts as c
from agent.fake_composition import integrate_literals
from agent.fake_integration import merge_exact_repetitions
from agent.graph import EssayState
from agent.stage_composition_nodes import integration_payload
from agent.stage_integration_contract import proposed_pair
from agent.stage_integration_selection import restore_baseline
from tests.composition_adversarial_support import prepared_context
from tests.test_composition_adversarial import BASELINE_TEXT


def state() -> EssayState:
    context = prepared_context()
    assert context.request is not None
    assert context.analysis is not None
    assert context.outline is not None
    assert context.writing_report is not None
    return EssayState(
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


@pytest.mark.parametrize("global_issue", [True, False])
def test_non_sentence_safety_issue_is_not_false_resolved(*, global_issue: bool) -> None:
    # Given a safety finding with section or global scope and no sentence IDs.
    payload = integration_payload(state())
    section_ids = () if global_issue else (c.SectionId("section-action"),)
    issue = c.IntegrationIssue(
        code="unsupported_claim",
        scope="baseline",
        sentence_ids=(),
        section_ids=section_ids,
        requirement_ids=(),
        gap_ids=(),
        status="open",
        message="Unsafe scope",
        handling="Remove",
    )
    # When a safe copy is restored.
    bundle, report = restore_baseline(payload, (issue,))
    # Then the affected scope is absent and an empty ID set cannot certify semantic resolution.
    assert report.issues[0].status == "open"
    assert c.render_body(bundle).strip()
    assert c.render_body(report.baseline_bundle) == BASELINE_TEXT
    assert not set(section_ids).intersection(
        sid for p in bundle.paragraphs for s in p.sentences for sid in s.section_ids
    )
    if global_issue:
        assert bundle.personalization == "non_personalized"
        assert report.selection == "general_fallback"


def test_summary_and_detail_are_not_false_duplicates() -> None:
    # Given different statements sharing a fact, plus identical text with distinct event evidence.
    baseline = integration_payload(state()).baseline_bundle
    first = baseline.paragraphs[0].sentences[0]
    detail = first.model_copy(
        update={
            "sentence_id": c.SentenceId("detail"),
            "text": "I sorted the library books by their labels.",
        }
    )
    other_event = first.model_copy(
        update={"sentence_id": c.SentenceId("other"), "fact_ids": (c.FactId("fact-garden"),)}
    )
    baseline = baseline.model_copy(
        update={
            "paragraphs": (
                baseline.paragraphs[0].model_copy(
                    update={"sentences": (first, detail, other_event)}
                ),
            )
        }
    )
    # When offline integration performs only exact text and evidence deduplication.
    paragraphs, edits = merge_exact_repetitions(baseline)
    # Then distinct meaning or event attribution is preserved unchanged.
    assert paragraphs == baseline.paragraphs
    assert all(edit.operation == "retain" for edit in edits)


def test_absent_comparison_rows_remain_explicitly_unassessed() -> None:
    # Given a valid identity proposal with omitted semantic comparison rows.

    payload = integration_payload(state())
    output = integrate_literals(payload).model_copy(
        update={"reverse_outline": (), "requirement_checks": ()}
    )
    # When server-owned correspondence is completed.
    bundle, report = proposed_pair(payload, output)
    # Then every actual paragraph and requirement appears without invented semantic certainty.
    assert {r.paragraph_id for r in report.reverse_outline} == {
        p.paragraph_id for p in bundle.paragraphs
    }
    assert {r.requirement_id for r in report.requirement_checks} == {
        r.requirement_id for r in payload.analysis.requirements
    }
    assert all(r.semantic_status == "unassessed" and r.gist is None for r in report.reverse_outline)
    assert all(r.after_state == "unassessed" for r in report.requirement_checks)
