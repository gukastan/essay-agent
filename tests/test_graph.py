import json
from pathlib import Path

import pytest

from tests.analysis_support import request_for
from tests.review_graph_support import Cycles, run_graph


@pytest.mark.parametrize("repairs", [0, 1, 2])
def test_six_stage_graph_has_bounded_six_eight_ten_node_traces(
    repairs: int, tmp_path: Path
) -> None:
    # Given zero, one, or two explicitly actionable title improvements.
    script = Cycles(repairs)
    # When the installed LangGraph executes with recursion limit20.
    final, trace = run_graph(request_for(), script, tmp_path)
    # Then one conditional router adds exactly two visits per repair, with one final result.
    assert len(trace) == 6 + 2 * repairs
    assert trace.count("title_and_review") == repairs + 1
    assert trace.count("repair_draft") == repairs
    assert trace.count("deliver_result") == 1
    assert final.repair_count == repairs
    assert "deliver_result" not in script.calls
    assert all(entry.outcome != "pending_review" for entry in final.repair_log)
    assert final.result.version_id == final.best_bundle.version_id == final.best_review.version_id
    assert all(entry.outcome == "accepted" for entry in final.repair_log)


def test_review_limit_is_not_a_quality_certificate(tmp_path: Path) -> None:
    # Given more current title defects than the allowed repair budget.
    script = Cycles(4)
    # When two repairs improve but do not complete the checks.
    final, trace = run_graph(request_for(), script, tmp_path)
    # Then the graph still delivers with unresolved issues and no third repair.
    assert len(trace) == 10
    assert final.result.stop_reason == "repair_limit"
    assert final.repair_count == 2
    assert any(issue.status == "open" for issue in final.best_review.issues)
    assert final.result.quality_report.display_status != "reviewed_draft"


def test_actual_six_stage_artifacts(tmp_path: Path) -> None:
    # Given zero/one/two repair runs and an empty-input run.
    scripts = [Cycles(count) for count in (0, 1, 2, 0)]
    requests = [request_for(), request_for(), request_for(), request_for("")]
    # When actual installed StateGraph streams each run to its one final package.
    runs = [
        run_graph(request, script, tmp_path / str(index))
        for index, (request, script) in enumerate(zip(requests, scripts, strict=True))
    ]
    # Then the reviewable JSON evidence records real drafts, reviews, repair logs and traces.
    directory = Path("../.omo/evidence/essay-agent")
    directory.mkdir(parents=True, exist_ok=True)
    artifacts = (
        (
            "task-6-candidate-history",
            [p.candidate_bundle for script in scripts for p in script.payloads],
        ),
        ("task-6-review-records", [run.best_review for run, _ in runs]),
        ("task-6-repair-log", [entry for run, _ in runs for entry in run.repair_log]),
        ("task-6-result-packages", [run.result for run, _ in runs]),
    )
    for name, values in artifacts:
        target = directory / (name + ".json")
        _ = target.write_text(
            "[\n" + ",\n".join(value.model_dump_json(indent=2) for value in values) + "\n]\n"
        )
        assert target.stat().st_size > 40
    _ = (directory / "task-6-trace.json").write_text(
        json.dumps([trace for _, trace in runs], indent=2)
    )
