import json
from pathlib import Path

import anyio
import pytest
from pydantic import ValidationError

from agent.contracts import (
    ContractContext,
    EssayRequest,
    QuestionKey,
    QuestionRegistryEntry,
    RevisionContext,
    SourceHistory,
    SourceId,
    UserSource,
    validate_contract,
)
from agent.essay_llm import ErrorKind
from agent.stage_analysis_models import AnalysisOutput
from agent.stage_structure_models import StructureOutput
from tests.analysis_support import COMMON, QUESTION, Responses, execute, request_for, run, seed
from tests.fixtures.schema_checks import assert_strict_schema


@pytest.mark.parametrize(
    "essay_request",
    [
        EssayRequest(),
        request_for(""),
        request_for(),
        request_for(
            "아파트 3곳에 수거함을 설치했습니다. 아이스팩을 수거하고 세척해 시장에 전달했습니다.",
            "도전 경험을 설명하세요.",
        ),
        request_for(
            "목표를 달성하지 못했습니다. 결과는 실패였습니다.", "실패 경험과 결과를 설명하세요."
        ),
    ],
)
def test_all_inputs_continue_with_contract_valid_outline(essay_request: EssayRequest) -> None:
    result = run(essay_request)
    validate_contract(
        ContractContext(
            evidence_version=result.evidence_version,
            sources=result.sources,
            facts=result.facts,
            analysis=result.analysis,
            outline=result.outline,
        )
    )
    assert result.outline.paragraphs
    assert sum(p.weight for p in result.outline.paragraphs) == 100
    assert all(p.weight > 0 for p in result.outline.paragraphs)


def test_icepack_facts_and_gaps() -> None:
    result = run(
        request_for(
            "아파트 3곳에 수거함을 설치했습니다. 아이스팩을 수거하고 세척해 시장에 전달했습니다.",
            "도전 경험의 행동과 배운 점을 설명하세요.",
        )
    )
    assert any("3곳" in fact.quote for fact in result.facts)
    assert any("R-learning" in gap.requirement_ids for gap in result.analysis.gaps)
    assert "참여율" not in result.outline.model_dump_json()


def test_missing_learning_has_no_prose_allocation() -> None:
    result = run(request_for())
    section = next(s for s in result.outline.sections if "R-learning" in s.requirement_ids)
    assert section.write_mode == "omit"
    assert section.allowed_content == ""
    assert section.gap_ids
    assert all(
        a.section_id != section.section_id for p in result.outline.paragraphs for a in p.allocations
    )
    assert any("기한" in fact.quote for fact in result.facts)


@pytest.mark.parametrize(
    ("text", "question", "present", "missing"),
    [
        (COMMON, "해결 경험과 결과를 설명하세요.", "기한", "R-learning"),
        ("자료 취합 시간을 20% 줄였습니다.", "경험의 수치 성과를 설명하세요.", "20%", "R-learning"),
        ("자료를 전달했습니다.", "경험을 수치와 함께 설명하세요.", "전달", "R-metric"),
        ("결과에 변화 없었습니다.", "경험과 결과를 설명하세요.", "변화 없", "R-learning"),
        (
            "책을 좋아하기 때문에 도서관에 관심이 있습니다.",
            "지원 동기를 설명하세요.",
            "좋아",
            "R-learning",
        ),
    ],
)
def test_provided_facts_and_optional_roles(
    text: str, question: str, present: str, missing: str
) -> None:
    result = run(request_for(text, question))
    assert any(present in fact.quote for fact in result.facts)
    if missing == "R-metric":
        assert any(missing in gap.requirement_ids for gap in result.analysis.gaps)
    else:
        assert all(
            requirement.requirement_id != missing for requirement in result.analysis.requirements
        )


def test_opinion_can_omit_experience() -> None:
    result = run(
        EssayRequest(
            question="업무에 대한 의견을 설명하세요.",
            user_views=(
                UserSource(
                    source_id=SourceId("view"), text="절차를 명확히 해야 한다고 생각합니다."
                ),
            ),
        )
    )
    assert result.outline.selected_experience_ids == ()
    assert result.outline.core_answer is not None


def test_unknown_limit_has_no_invented_cap() -> None:
    result = run(EssayRequest())
    assert result.outline.budget.subtitle_reserved_chars is None
    assert result.outline.budget.usable_body_chars is None
    assert all(p.target_chars is None for p in result.outline.paragraphs)
    assert result.outline.core_answer is None


@pytest.mark.parametrize(
    "kind", [ErrorKind.INCOMPLETE, ErrorKind.REFUSAL, ErrorKind.AUTH, ErrorKind.TIMEOUT]
)
def test_analysis_failure_preserves_unparsed_question(kind: ErrorKind) -> None:
    responses = Responses(failing_stage="analyze_context", error_kind=kind)
    result = run(request_for(), responses)
    requirement = next(
        r for r in result.analysis.requirements if r.requirement_id == "R-unparsed-question"
    )
    assert requirement.description == QUESTION
    assert requirement.resolution == "unparsed"
    assert result.sources
    assert result.facts == ()
    assert result.outline.requirement_map[0].planned_coverage == "unfilled"
    assert responses.calls.count("analyze_context") == (2 if kind == ErrorKind.TIMEOUT else 1)
    assert responses.calls[-1] == "plan_structure"


def test_structure_fallback_preserves_compound_requirements() -> None:
    result = run(request_for(), Responses(failing_stage="plan_structure"))
    assert {m.requirement_id for m in result.outline.requirement_map} == {
        r.requirement_id for r in result.analysis.requirements
    }
    assert result.outline.paragraphs[0].weight == 100
    assert result.technical_issues[0].node == "plan_structure"


def test_source_reference_error_retries_then_uses_conservative_fallback() -> None:
    def corrupt(output: AnalysisOutput) -> AnalysisOutput:
        fact = output.facts[0].model_copy(update={"source_id": SourceId("foreign")})
        return output.model_copy(update={"facts": (fact, *output.facts[1:])})

    responses = Responses(analysis_edit=corrupt)
    result = run(request_for(), responses)
    assert responses.calls.count("analyze_context") == 2
    assert result.facts == ()
    assert result.analysis.analysis_status == "unavailable"


def test_partial_analysis_preserves_valid_facts_and_unparsed_question() -> None:
    def partial(output: AnalysisOutput) -> AnalysisOutput:
        return output.model_copy(
            update={"analysis": output.analysis.model_copy(update={"analysis_status": "partial"})}
        )

    result = run(request_for(), Responses(analysis_edit=partial))
    assert result.facts
    assert result.analysis.analysis_status == "partial"
    assert any(r.requirement_id == "R-unparsed-question" for r in result.analysis.requirements)


def test_explicit_source_correction_supersedes_old_fact() -> None:
    state = seed(request_for("아파트 4곳에 설치했습니다."))
    state["revision_context"] = RevisionContext(
        source_history=(
            SourceHistory(
                source_id=SourceId("event"),
                previous_text="아파트 3곳에 설치했습니다.",
                current_text="아파트 4곳에 설치했습니다.",
                status="active",
                evidence_version=state["evidence_version"],
            ),
        ),
        question_registry=(),
    )
    result = anyio.run(execute, state, Responses())
    assert any("4곳" in f.quote for f in result.facts)
    assert all("3곳" not in f.quote for f in result.facts)


def test_unavailable_question_survives_style_only_revision() -> None:
    state = seed(
        request_for().model_copy(update={"revision_instruction": "더 담백하게 써 주세요."})
    )
    state["revision_context"] = RevisionContext(
        source_history=(),
        question_registry=(
            QuestionRegistryEntry(
                question_key=QuestionKey("existing-learning"),
                subject_source_ids=(SourceId("user:event"),),
                missing_detail="실제 배운 점",
                question_status="unavailable",
                user_response_source_id=None,
            ),
        ),
    )
    result = anyio.run(execute, state, Responses())
    gap = next(g for g in result.analysis.gaps if "R-learning" in g.requirement_ids)
    assert gap.question_key == "existing-learning"
    assert gap.question_status == "unavailable"
    assert gap.question is None


def test_snapshots_immutable_and_strict_output_schemas() -> None:
    result = run(request_for("가 😀 자료를 전달했습니다."))
    assert result.facts[0].quote == result.sources[0].text
    with pytest.raises(ValidationError):
        result.sources[0].text = "changed"
    assert_strict_schema(AnalysisOutput)
    assert_strict_schema(StructureOutput)


def test_capture_analysis_outline_surface() -> None:
    results = [
        run(request)
        for request in (EssayRequest(), request_for(), request_for("자료를 전달했습니다."))
    ]
    artifact = (
        Path(__file__).resolve().parents[2]
        / ".omo/evidence/essay-agent/task-4-analysis-outline.json"
    )
    artifact.parent.mkdir(parents=True, exist_ok=True)
    _ = artifact.write_text(
        json.dumps(
            [json.loads(result.model_dump_json()) for result in results],
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    assert all(result.outline.paragraphs for result in results)


def test_implicit_resolution_keeps_qualitative_result_and_missing_core_gap() -> None:
    result = run(
        request_for(
            "공통 양식을 만들었습니다. 자료를 기한 내 취합했습니다.",
            "문제를 해결한 경험을 설명하세요.",
        )
    )
    requirement = next(r for r in result.analysis.requirements if r.requirement_id == "R-result")
    assert requirement.information_role == "logical_core"
    assert requirement.required_by_prompt is False
    assert requirement.application_condition
    section = next(s for s in result.outline.sections if "R-result" in s.requirement_ids)
    assert "기한" in section.allowed_content


def test_missing_core_info_kept_as_gap() -> None:
    result = run(request_for("공통 양식을 만들었습니다.", "문제를 해결한 경험을 설명하세요."))
    result_requirement = next(
        r for r in result.analysis.requirements if r.requirement_id == "R-result"
    )
    assert result_requirement.information_role == "logical_core"
    assert any("R-result" in gap.requirement_ids for gap in result.analysis.gaps)
    section = next(s for s in result.outline.sections if "R-result" in s.requirement_ids)
    assert section.write_mode == "omit"


def test_no_result_vs_unknown_distinguished() -> None:
    result = run(request_for("결과에 변화 없었습니다.", "결과를 설명하세요."))
    assert any("변화 없" in fact.quote for fact in result.facts)
    assert all("R-result" not in gap.requirement_ids for gap in result.analysis.gaps)
