from pathlib import Path

import pytest

from agent.delivery_structure import structure_for
from agent.delivery_suggestions import suggestions_for
from agent.review_selection import control_for
from tests.fixtures.cases import ContractCase
from tests.review_adversarial_support import run_case


def test_duplicate_gap_issue_and_semantic_guidance_merge_all_origins() -> None:
    # Given one current gap reported as a model suggestion and a missing-info issue.
    ctx = ContractCase.load("complete.json").parse()
    assert ctx.bundle is not None
    assert ctx.review is not None
    assert ctx.analysis is not None
    assert ctx.outline is not None
    original = ctx.review.suggestions[0]
    # When delivery groups causes rather than repeating human labels.
    rows = suggestions_for(ctx.bundle, ctx.review, ctx.analysis, ctx.outline)
    # Then semantic guidance survives in one row with both current origin types.
    assert len(rows) == 1
    assert rows[0].issue_ids == original.issue_ids
    assert rows[0].gap_ids == original.gap_ids
    assert rows[0].next_action == original.next_action
    assert rows[0].priority == 1


@pytest.mark.parametrize("foreign", ["issue_ids", "gap_ids", "requirement_ids", "sentence_ids"])
def test_foreign_guidance_is_discarded(foreign: str) -> None:
    # Given useful-looking text whose declared origin does not belong to the run.
    ctx = ContractCase.load("complete.json").parse()
    assert ctx.bundle is not None
    assert ctx.review is not None
    assert ctx.analysis is not None
    assert ctx.outline is not None
    forged = ctx.review.suggestions[0].model_copy(
        update={foreign: ("foreign",), "next_action": "Foreign action"}
    )
    # When only current origin-backed guidance is assembled.
    rows = suggestions_for(
        ctx.bundle,
        ctx.review.model_copy(update={"suggestions": (forged,)}),
        ctx.analysis,
        ctx.outline,
    )
    # Then the foreign guidance cannot displace valid current gap advice.
    assert rows
    assert all(row.next_action != forged.next_action for row in rows)


def test_unavailable_gap_keeps_guidance_without_reasking() -> None:
    # Given a preserved unavailable information state and a stale proposed question in review.
    ctx = ContractCase.load("complete.json").parse()
    assert ctx.bundle is not None
    assert ctx.review is not None
    assert ctx.analysis is not None
    assert ctx.outline is not None
    analysis = ctx.analysis.model_copy(
        update={
            "gaps": tuple(
                g.model_copy(update={"question_status": "unavailable"}) for g in ctx.analysis.gaps
            )
        }
    )
    # When current analysis owns question state.
    rows = suggestions_for(ctx.bundle, ctx.review, analysis, ctx.outline)
    # Then the gap stays visible but no answer request is repeated.
    assert len(rows) == 1
    assert rows[0].question_status == "unavailable"
    assert rows[0].example_question is None


def test_unmet_without_missing_information_does_not_claim_missing_input() -> None:
    # Given supplied evidence and a model omission without an actionable target.
    ctx = ContractCase.load("complete.json").parse()
    assert ctx.review is not None
    review = ctx.review.model_copy(update={"issues": (), "repair_targets": ()})
    # When the stop authority chooses a normal delivery reason.
    control = control_for(review, 0)
    # Then unmet coverage alone is not relabeled as unavailable personal information.
    assert control.reason == "no_fixable_issue"


def test_structure_order_follows_sentence_order_within_one_paragraph() -> None:
    # Given logical parts reordered within the same actual paragraph.
    ctx = ContractCase.load("complete.json").parse()
    assert ctx.bundle is not None
    assert ctx.review is not None
    assert ctx.outline is not None
    paragraph = ctx.bundle.paragraphs[0]
    bundle = ctx.bundle.model_copy(
        update={
            "paragraphs": (
                paragraph.model_copy(update={"sentences": tuple(reversed(paragraph.sentences))}),
                *ctx.bundle.paragraphs[1:],
            )
        }
    )
    # When current location explanations are assembled.
    rows = structure_for(bundle, ctx.review, ctx.outline)
    # Then first actual appearance wins and unwritten planned rows remain last.
    assert rows[0].section_id == paragraph.sentences[1].section_ids[0]
    assert rows[-1].coverage == "not_expressed"


def test_stale_all_pair_fallback_replaces_prior_normal_stop_reason(tmp_path: Path) -> None:
    # Given two stale review pairs after a normal prior no-fixable stop.
    receipt = run_case("stale_all", tmp_path)
    # When delivery must create a new fallback pair without another model call.
    result = receipt.result
    # Then the terminal reason describes this actual technical fallback.
    assert result.stop_reason == "fallback_after_error"
    assert result.generation_status == "completed_with_fallback"
