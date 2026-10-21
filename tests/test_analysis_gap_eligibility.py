from typing import Literal, assert_never

import anyio
import pytest

from agent.contracts import QuestionKey, QuestionRegistryEntry, RevisionContext, SourceId
from agent.stage_analysis_models import AnalysisOutput
from agent.stage_analysis_rules import missing_gap
from tests.analysis_support import Responses, execute, request_for, run, seed

Mode = Literal["excluded", "not_applicable", "conflicting"]


def ineligible(output: AnalysisOutput, mode: Mode) -> AnalysisOutput:
    requirements = tuple(
        r.model_copy(update={"required_by_prompt": False}) for r in output.analysis.requirements
    )
    links = output.analysis.evidence_links
    facts = output.facts
    match mode:
        case "excluded":
            links = tuple(link.model_copy(update={"information_role": "exclude"}) for link in links)
        case "not_applicable":
            links = tuple(
                link.model_copy(update={"applicability": "not_applicable"}) for link in links
            )
        case "conflicting":
            facts = tuple(
                fact.model_copy(update={"information_state": "conflicting"}) for fact in facts
            )
        case _:
            assert_never(mode)
    gaps = tuple(
        missing_gap(r).model_copy(
            update={"question_status": "resolved", "question": "본인 역할을 알려주세요."}
        )
        for r in requirements
    )
    return output.model_copy(
        update={
            "facts": facts,
            "analysis": output.analysis.model_copy(
                update={"requirements": requirements, "evidence_links": links, "gaps": gaps}
            ),
        }
    )


@pytest.mark.parametrize("mode", ["excluded", "not_applicable", "conflicting"])
@pytest.mark.parametrize("prior_status", [None, "unavailable", "not_needed"])
def test_ineligible_evidence_cannot_resolve_gap(
    mode: Mode,
    prior_status: Literal["unavailable", "not_needed"] | None,
) -> None:
    state = seed(request_for("자료 취합을 담당했습니다.", "본인의 역할을 설명하세요."))
    if prior_status is not None:
        state["revision_context"] = RevisionContext(
            source_history=(),
            question_registry=(
                QuestionRegistryEntry(
                    question_key=QuestionKey("role"),
                    subject_source_ids=(SourceId("user:event"),),
                    missing_detail="본인 역할",
                    question_status=prior_status,
                    user_response_source_id=None,
                ),
            ),
        )
    result = anyio.run(
        execute, state, Responses(analysis_edit=lambda value: ineligible(value, mode))
    )
    assert result.analysis.gaps[0].question_status == (prior_status or "proposed")
    if prior_status is None:
        assert result.analysis.gaps[0].question == "본인 역할을 알려주세요."
    else:
        assert result.analysis.gaps[0].question is None
    assert result.outline.core_answer is None
    assert result.technical_issues == ()


def test_available_link_to_conflicting_fact_creates_gap_before_structure_fallback() -> None:
    def omitted_gap(output: AnalysisOutput) -> AnalysisOutput:
        invalid = ineligible(output, "conflicting")
        return invalid.model_copy(
            update={"analysis": invalid.analysis.model_copy(update={"gaps": ()})}
        )

    result = run(
        request_for("자료 취합을 담당했습니다.", "본인의 역할을 설명하세요."),
        Responses(analysis_edit=omitted_gap, failing_stage="plan_structure"),
    )
    assert result.analysis.gaps
    assert result.analysis.gaps[0].question_status == "proposed"
    assert result.outline.requirement_map[0].planned_coverage == "unfilled"
    assert result.outline.paragraphs


def test_eligible_current_evidence_can_resolve_gap() -> None:
    def resolved(output: AnalysisOutput) -> AnalysisOutput:
        gaps = tuple(
            missing_gap(r).model_copy(
                update={"question_status": "resolved", "question": "본인 역할을 알려주세요."}
            )
            for r in output.analysis.requirements
        )
        return output.model_copy(
            update={"analysis": output.analysis.model_copy(update={"gaps": gaps})}
        )

    result = run(
        request_for("자료 취합을 담당했습니다.", "본인의 역할을 설명하세요."),
        Responses(analysis_edit=resolved),
    )
    assert result.analysis.gaps[0].question_status == "resolved"
    assert result.analysis.gaps[0].question is None
    assert result.outline.requirement_map[0].planned_coverage == "planned_supported"
