from pathlib import Path

import pytest

from agent import contracts as c
from tests.analysis_support import request_for
from tests.review_graph_support import Cycles, run_graph


@pytest.mark.parametrize("text", ["", "회의 의견을 기록했습니다."])
def test_low_information_delivers_title_prose_structure_and_suggestions(
    text: str, tmp_path: Path
) -> None:
    # Given sparse or empty personal information.
    script = Cycles()
    # When all six stages execute without an initial question gate.
    final, trace = run_graph(request_for(text), script, tmp_path)
    # Then all four deliverables remain accessible with honest current coverage.
    assert final.result.subtitle.strip()
    assert final.result.body.strip()
    assert final.result.structure
    assert final.result.suggestions
    assert len(trace) == 6
    assert final.repair_count == 0
    assert final.result.stop_reason == "missing_info_only"
    assert all(
        row.coverage != "supported" for row in final.result.structure if not row.actual_sentence_ids
    )


def test_forbidden_title_remains_display_only(tmp_path: Path) -> None:
    # Given a current explicit no-title instruction.
    request = request_for(question="협업 경험을 설명하세요. 제목 금지")
    # When the same body receives a reference title.
    final, _ = run_graph(request, Cycles(), tmp_path)
    # Then copying and counting exclude the display-only title.
    assert final.result.subtitle
    assert final.result.subtitle_placement == "display_only"
    assert final.result.copy_text == final.result.body
    assert not final.result.quality_report.length_check.includes_subtitle


@pytest.mark.parametrize("include_title", [True, False])
def test_final_length_counts_actual_title_and_separator(
    tmp_path: Path, *, include_title: bool
) -> None:
    # Given a concrete length policy independent from title placement.
    request = request_for().model_copy(
        update={"length_policy": c.LengthPolicy(max_chars=600, include_subtitle=include_title)}
    )
    # When final selected prose is rendered.
    final, _ = run_graph(request, Cycles(), tmp_path)
    # Then the final count uses actual title bytes as Unicode characters, not reservation.
    bundle, report = final.best_bundle, final.result.quality_report.length_check
    assert final.result.character_count == c.count_characters(
        c.counted_text(bundle, request.length_policy), request.length_policy
    )
    assert report.counted_chars == report.body_chars + (
        report.subtitle_chars + report.separator_chars if include_title else 0
    )
    assert final.result.copy_text == final.result.subtitle + "\n\n" + final.result.body


@pytest.mark.parametrize("repairs", [0, 1])
def test_explicit_composition_fallback_survives_successful_review_and_title_repair(
    repairs: int, tmp_path: Path
) -> None:
    # Given stage3 technical failure and an explicit unmapped general fallback.
    script = Cycles(repairs, failure="write_sections")
    # When successful review and optional title repair retain that same fallback.
    final, _ = run_graph(request_for(""), script, tmp_path)
    # Then current fallback provenance permits review without creating personal mappings.
    assert final.result.body.strip()
    assert final.result.personalization == "non_personalized"
    assert final.repair_count == repairs
    assert final.best_review.review_status == "performed"
    assert all(
        not s.section_ids and not s.fact_ids
        for p in final.best_bundle.paragraphs
        for s in p.sentences
    )


def test_known_title_prohibition_survives_full_review_error(tmp_path: Path) -> None:
    # Given a no-title instruction and exhausted review calls.
    request = request_for(question="협업 경험을 설명하세요. 제목 금지")
    # When the complete review falls back to neutral prose.
    final, _ = run_graph(request, Cycles(failure="title_and_review"), tmp_path)
    # Then the reference title remains outside submission copy despite review failure.
    assert final.result.subtitle_placement == "display_only"
    assert final.result.copy_text == final.result.body
    assert final.result.quality_report.review_status == "unavailable"


def test_fixed_title_survives_final_unsafe_content_cleanup(tmp_path: Path) -> None:
    # Given a quoted fixed title and current unsupported body findings.
    request = request_for(question='협업 경험을 설명하세요. 고정 제목: "작성 내용"')
    # When bounded review/repair concludes with a neutral safety fallback.
    final, _ = run_graph(request, Cycles(unsafe=True), tmp_path)
    # Then the submission label is preserved as formatting rather than invented evidence.
    assert final.result.subtitle == "작성 내용"
    assert final.best_bundle.subtitle_fact_ids == ()
    assert final.result.personalization == "non_personalized"
    assert final.best_review.review_status == "partial"


def test_tiny_limit_remains_explicit_required_guidance_without_rejection(tmp_path: Path) -> None:
    # Given a limit too small to hold the existing truthful readable draft.
    request = request_for().model_copy(update={"length_policy": c.LengthPolicy(max_chars=1)})
    # When actual length is measured even if the model omitted a length issue.
    final, _ = run_graph(request, Cycles(), tmp_path)
    # Then draft delivery continues and the real submission issue is never a clean pass.
    assert final.result.body.strip()
    assert final.result.quality_report.length_check.status == "over"
    assert final.result.quality_report.display_status == "needs_attention"
    assert any(
        row.area == "submission" and row.category == "required_edit"
        for row in final.result.suggestions
    )
    assert final.result.quality_report.required_item_count > 0
