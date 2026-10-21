from pathlib import Path

import pytest

from agent import contracts as c
from agent.essay_llm import ErrorKind, Stage
from tests.analysis_support import COMMON, Responses, request_for
from tests.composition_support import run_composition


@pytest.mark.parametrize("text", ["", "회의 의견을 기록했습니다.", COMMON])
def test_sparse_input_produces_prose(text: str, tmp_path: Path) -> None:
    # Given current personal input ranging from empty to detailed.
    request = request_for(text)
    # When the actual four-stage StateGraph executes.
    result, script = run_composition(request, tmp_path)
    # Then it yields readable prose and exactly one logical call at each stage.
    assert c.render_body(result.candidate_bundle).strip()
    assert script.calls == [
        "analyze_context",
        "plan_structure",
        "write_sections",
        "integrate_draft",
    ]
    assert result.candidate_bundle.subtitle is None
    assert result.candidate_bundle.evidence_version == result.evidence_version
    if not text:
        assert result.candidate_bundle.personalization == "non_personalized"
        assert all(not s.fact_ids for p in result.candidate_bundle.paragraphs for s in p.sentences)


@pytest.mark.parametrize("stage", ["write_sections", "integrate_draft"])
def test_generation_failure_preserves_readable_output(stage: Stage, tmp_path: Path) -> None:
    # Given a timed-out generation at either composition boundary.
    script = Responses(failing_stage=stage, error_kind=ErrorKind.TIMEOUT)
    # When the provider exhausts its bounded retry.
    result, _ = run_composition(request_for(), tmp_path, script)
    # Then output is still delivered and failure usage never triggers a quality loop.
    assert c.render_body(result.candidate_bundle).strip()
    assert script.calls.count(stage) == 2
    assert any(issue.node == stage for issue in result.technical_issues)
    assert all(row.gist is None for row in result.integration_report.reverse_outline)
    if stage == "integrate_draft":
        assert result.integration_report.selection == "baseline"
        assert result.candidate_bundle == result.integration_report.baseline_bundle
    else:
        assert result.writing_report.fallback_sentences
        assert result.candidate_bundle.personalization == "non_personalized"


@pytest.mark.parametrize("include_title", [True, False])
@pytest.mark.parametrize("limit", [None, 20, 600])
def test_length_snapshot_is_actual_body_only(
    limit: int | None, tmp_path: Path, *, include_title: bool
) -> None:
    # Given an optional limit and explicit title accounting policy.
    policy = c.LengthPolicy(
        max_chars=limit, include_spaces=True, include_newlines=True, include_subtitle=include_title
    )
    request = request_for().model_copy(update={"length_policy": policy})
    # When prose is composed without padding to its target.
    result, _ = run_composition(request, tmp_path)
    # Then the snapshot measures current NFC body and leaves title accounting pending.
    snapshot = result.integration_report.length_after
    assert snapshot.body_chars == c.count_characters(
        c.render_body(result.candidate_bundle), request.length_policy
    )
    assert snapshot.measurement_scope == "body_only"
    assert snapshot.subtitle_pending is include_title
    assert result.candidate_bundle.subtitle is None
    if limit == 600:
        assert snapshot.body_chars < limit


def test_omit_section_has_no_invented_learning(tmp_path: Path) -> None:
    # Given actions and results but no stated learning.
    request = request_for()
    # When all planned sections are rendered.
    result, _ = run_composition(request, tmp_path)
    # Then omitted allocations carry no personal prose and all facts remain exact quotes.
    omitted = {s.section_id for s in result.outline.sections if s.write_mode == "omit"}
    assert omitted
    assert all(not d.allocations for d in result.section_drafts if d.section_id in omitted)
    facts = {f.fact_id: f for f in result.facts}
    for paragraph in result.candidate_bundle.paragraphs:
        for sentence in paragraph.sentences:
            assert not omitted.intersection(sentence.section_ids)
            assert all(sentence.text == facts[fid].quote for fid in sentence.fact_ids)


def test_duplicate_role_removed_but_requirement_retained(tmp_path: Path) -> None:
    # Given the same quote allocated to multiple roles.
    request = request_for()
    # When exact current quote repetition is integrated.
    result, _ = run_composition(request, tmp_path)
    # Then duplicate text/evidence within a paragraph is merged with trace and section coverage.
    before = result.integration_report.baseline_bundle
    after = result.candidate_bundle
    assert any(edit.operation == "merge" for edit in result.integration_report.edits)
    assert {sid for p in before.paragraphs for s in p.sentences for sid in s.section_ids} == {
        sid for p in after.paragraphs for s in p.sentences for sid in s.section_ids
    }
    for paragraph in after.paragraphs:
        keys = [(s.text, s.fact_ids) for s in paragraph.sentences]
        assert len(keys) == len(set(keys))


def test_actual_graph_composition_artifacts(tmp_path: Path) -> None:
    # Given separate empty, sparse, and supplied personal statements.
    requests = (request_for(""), request_for("회의 의견을 기록했습니다."), request_for())
    # When each request executes the installed four-node graph and produces typed reports.
    results = [
        run_composition(request, tmp_path / str(index))[0] for index, request in enumerate(requests)
    ]
    # Then the manually reviewable artifacts contain actual current draft/report objects.
    directory = Path("../.omo/evidence/essay-agent")
    directory.mkdir(parents=True, exist_ok=True)
    for name, values in (
        ("task-5-draft-bundles", [r.candidate_bundle for r in results]),
        ("task-5-writing-reports", [r.writing_report for r in results]),
        ("task-5-integration-reports", [r.integration_report for r in results]),
    ):
        target = directory / (name + ".json")
        _ = target.write_text(
            "[\n" + ",\n".join(value.model_dump_json(indent=2) for value in values) + "\n]\n"
        )
        assert target.stat().st_size > 100
