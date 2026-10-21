from pathlib import Path

import pytest

from agent import contracts as c
from tests.review_adversarial_contracts import Scenario
from tests.review_adversarial_support import run_case


def test_supported_control_delivers_matching_draft_without_repair(tmp_path: Path) -> None:
    # Given explicit positive checks for every current supplied statement.
    # When review and deterministic delivery process the valid current draft.
    receipt = run_case("control", tmp_path)
    # Then the original body and supported coverage survive without an improvement call.
    assert receipt.result.body == c.render_body(receipt.initial)
    assert receipt.calls == ("title_and_review",)
    assert receipt.repair_count == 0
    assert all(row.coverage == "supported" for row in receipt.result.structure)
    assert receipt.result.quality_report.display_status == "reviewed_draft"


@pytest.mark.parametrize("scenario", ["lost_learning", "fabricated"])
def test_shorter_answer_loss_or_fabricated_repair_never_replaces_valid_best(
    scenario: Scenario,
    tmp_path: Path,
) -> None:
    # Given a grounded baseline and a deletion or invented claim using known fact IDs.
    # When that proposed repair is reviewed against the current sources and required answer.
    receipt = run_case(scenario, tmp_path)
    # Then the exact valid body remains selected rather than the latest harmful proposal.
    assert receipt.result.body == c.render_body(receipt.initial)
    assert receipt.repair_count == 1
    assert receipt.calls == ("title_and_review", "repair_draft", "title_and_review")
    assert receipt.repair_log[0].outcome == "rejected"
    assert receipt.result.stop_reason == "no_improvement"
    assert "sentence-learning" in {
        s.sentence_id for p in receipt.selected.paragraphs for s in p.sentences
    }
    assert "fabricated-sentence" not in {
        s.sentence_id for p in receipt.selected.paragraphs for s in p.sentences
    }


def test_met_requirement_without_positive_current_checks_is_not_supported(tmp_path: Path) -> None:
    # Given met requirement claims but every current sentence check explicitly unassessed.
    # When final coverage and user-facing status are assembled.
    receipt = run_case("no_positive", tmp_path)
    # Then missing positive evidence cannot become supported coverage or a reviewed pass.
    assert receipt.result.body == c.render_body(receipt.initial)
    assert all(row.coverage == "unassessed" for row in receipt.result.structure)
    assert all(
        check.status != "met"
        for check in receipt.review.requirement_checks
        if check.requirement_id in ("req-action", "req-result")
    )
    assert receipt.result.quality_report.display_status == "review_incomplete"


@pytest.mark.parametrize("scenario", ["source_title", "title_only"])
def test_source_only_title_cannot_supply_a_missing_body_answer(
    scenario: Scenario, tmp_path: Path
) -> None:
    # Given a title claim linked only to a supplied source fact, with no current body sentence link.
    # When title selection and body-independent requirement checks run together.
    receipt = run_case(scenario, tmp_path)
    # Then invalid title evidence is replaced while valid body review and prose remain available.
    assert receipt.result.body == c.render_body(receipt.initial)
    assert receipt.selected.subtitle_fact_ids == ()
    assert receipt.result.subtitle != "A lesson in agreement"
    assert receipt.calls == ("title_and_review",)
    if scenario == "title_only":
        check = next(
            row for row in receipt.review.requirement_checks if row.requirement_id == "req-result"
        )
        assert check.status != "met"
        assert not check.body_sentence_ids
    else:
        assert receipt.review.review_status == "performed"
        assert all(row.status == "source_supported" for row in receipt.review.sentence_checks)


@pytest.mark.parametrize("scenario", ["review_error", "repair_error"])
def test_exhausted_review_or_repair_still_delivers_readable_matching_output(
    scenario: Scenario,
    tmp_path: Path,
) -> None:
    # Given normalized timeouts on both technical attempts of review or repair.
    # When the bounded failure path reaches delivery without another quality loop.
    receipt = run_case(scenario, tmp_path)
    # Then a readable version-matched result is returned with an honest stop reason.
    assert receipt.result.stop_reason == "fallback_after_error"
    if scenario == "review_error":
        assert receipt.calls == ("title_and_review", "title_and_review")
        assert receipt.repair_count == 0
        assert receipt.result.personalization == "non_personalized"
        assert receipt.result.quality_report.review_status == "unavailable"
    else:
        assert receipt.calls == ("title_and_review", "repair_draft", "repair_draft")
        assert receipt.repair_count == 1
        assert receipt.repair_log[0].outcome == "failed"
        assert receipt.result.body == c.render_body(receipt.initial)


def test_title_only_repairs_share_two_attempt_budget(tmp_path: Path) -> None:
    # Given two explicit title defects that each successive title-only repair resolves in part.
    # When review revisits the changing title while the supplied body stays identical.
    receipt = run_case("title_budget", tmp_path)
    # Then exactly two repair visits share the common budget and no body prose is discarded.
    assert receipt.repair_count == 2
    assert receipt.calls == (
        "title_and_review",
        "repair_draft",
        "title_and_review",
        "repair_draft",
        "title_and_review",
    )
    assert len(receipt.repair_log) == 2
    assert all(entry.outcome == "accepted" for entry in receipt.repair_log)
    assert receipt.result.body == c.render_body(receipt.initial)
    assert receipt.result.stop_reason == "repair_limit"


@pytest.mark.parametrize("scenario", ["omitted", "missing"])
def test_supplied_omission_can_repair_but_missing_information_does_not_loop(
    scenario: Scenario,
    tmp_path: Path,
) -> None:
    # Given the same absent body answer with either available source evidence or a true source gap.
    # When review decides whether any current evidence can fill that answer.
    receipt = run_case(scenario, tmp_path)
    # Then only supplied omission triggers repair; missing information still permits delivery.
    if scenario == "omitted":
        assert receipt.repair_count == 1
        assert "I learned to agree on a method before starting." in receipt.result.body
        assert receipt.repair_log[0].outcome == "accepted"
    else:
        assert receipt.repair_count == 0
        assert receipt.calls == ("title_and_review",)
        assert receipt.result.stop_reason == "missing_info_only"
        assert (
            next(
                row for row in receipt.result.structure if row.section_id == "section-result"
            ).coverage
            == "not_expressed"
        )


@pytest.mark.parametrize("scenario", ["unavailable", "resolved"])
def test_unavailable_or_resolved_questions_are_not_reasked(
    scenario: Scenario, tmp_path: Path
) -> None:
    # Given a current unresolved body gap with an explicit existing question disposition.
    # When delivery builds suggestions from current gaps and review findings.
    receipt = run_case(scenario, tmp_path)
    # Then the disposition prevents repeating the same question without suppressing the draft.
    matching = [s for s in receipt.result.suggestions if s.question_key == "question-result"]
    if scenario == "resolved":
        assert not matching
    else:
        assert matching
        assert all(
            s.question_status == "unavailable" and s.example_question is None for s in matching
        )


@pytest.mark.parametrize("scenario", ["stale_best", "stale_all"])
def test_stale_review_uses_matching_pair_or_safe_fallback(
    scenario: Scenario, tmp_path: Path
) -> None:
    # Given a stale best review, optionally with every retained review stale as well.
    # When Python-only delivery resolves a version-matched pair.
    receipt = run_case(scenario, tmp_path)
    # Then an existing matching pair wins, otherwise readable nonpersonalized fallback is explicit.
    assert receipt.calls == ("title_and_review",)
    if scenario == "stale_best":
        assert receipt.result.body == c.render_body(receipt.initial)
    else:
        assert receipt.result.personalization == "non_personalized"
        assert receipt.result.generation_status == "completed_with_fallback"
        assert receipt.result.quality_report.review_status == "unavailable"


def test_all_unsafe_cleanup_refreshes_version_personalization_and_locations(tmp_path: Path) -> None:
    # Given explicit unsupported checks for every current personal statement.
    # When bounded review/repair completes and safety cleanup removes those statements.
    receipt = run_case("all_unsafe", tmp_path)
    # Then a fresh readable general draft has no stale personal attribution or body locations.
    assert receipt.selected.version_id != receipt.initial.version_id
    assert receipt.result.personalization == "non_personalized"
    assert all(
        not s.section_ids and not s.fact_ids
        for p in receipt.selected.paragraphs
        for s in p.sentences
    )
    assert all(
        row.coverage == "not_expressed" and not row.locations and not row.actual_sentence_ids
        for row in receipt.result.structure
    )
    assert receipt.result.quality_report.display_status == "review_incomplete"
    assert len(receipt.calls) <= 5


def test_shorter_repair_swapping_one_unsafe_claim_for_another_is_rejected(tmp_path: Path) -> None:
    # Given one unsafe baseline claim and a shorter repair introducing a different unsafe claim.
    # When review reports the same unsafe count but changed claim identity.
    receipt = run_case("unsafe_swap", tmp_path)
    # Then new harm is rejected and safety cleanup preserves the other original supplied prose.
    assert receipt.repair_count == 1
    assert receipt.repair_log[0].outcome == "rejected"
    assert receipt.result.stop_reason == "no_improvement"
    assert receipt.result.body == (
        "I watered the garden.\n\nMy task was sorting books. "
        "I learned to agree on a method before starting."
    )
    assert "fabricated-sentence" not in {
        s.sentence_id for p in receipt.selected.paragraphs for s in p.sentences
    }
