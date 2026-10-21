import anyio
import pytest

from agent.contracts import EssayRequest, SourceId, UserSource
from agent.mcp_materials import CompanyMaterial
from agent.stage_analysis_models import AnalysisOutput
from agent.stage_structure_models import StructureOutput
from tests.analysis_support import Responses, execute, request_for, run, seed


def test_multiple_experiences_cover_distinct_requirements() -> None:
    result = run(
        EssayRequest(
            question="두 경험을 설명하세요.",
            experiences=(
                UserSource(source_id=SourceId("first"), text="자료를 작성했습니다."),
                UserSource(source_id=SourceId("second"), text="수거함을 설치했습니다."),
            ),
        )
    )
    assert len(result.outline.selected_experience_ids) == 2
    assert len(result.outline.selected_candidate_ids) == 2
    for section in result.outline.sections:
        assert {f.experience_id for f in result.facts if f.fact_id in section.fact_ids} <= set(
            section.experience_ids
        )


def test_second_required_experience_not_invented() -> None:
    result = run(request_for("자료를 작성했습니다.", "두 경험을 설명하세요."))
    assert len(result.outline.selected_experience_ids) == 1
    second = next(
        m for m in result.outline.requirement_map if m.requirement_id == "R-second-experience"
    )
    assert second.planned_coverage == "unfilled"
    assert second.gap_ids


def test_candidate_tie_uses_source_order() -> None:
    result = run(
        EssayRequest(
            question="경험을 설명하세요.",
            experiences=(
                UserSource(source_id=SourceId("z"), text="자료를 전달했습니다."),
                UserSource(source_id=SourceId("a"), text="자료를 전달했습니다."),
            ),
        )
    )
    assert result.outline.selected_candidate_ids == ("C1",)
    assert result.outline.selected_experience_ids == ("E1",)


def exclude_first(output: AnalysisOutput) -> AnalysisOutput:
    links = tuple(
        link.model_copy(update={"information_role": "exclude", "use_status": "excluded"})
        if link.candidate_id == "C1"
        else link
        for link in output.analysis.evidence_links
    )
    return output.model_copy(
        update={"analysis": output.analysis.model_copy(update={"evidence_links": links})}
    )


def test_direct_fit_beats_large_unrelated_metric() -> None:
    result = run(
        EssayRequest(
            question="협업 경험을 설명하세요.",
            experiences=(
                UserSource(source_id=SourceId("unrelated"), text="개인 매출을 900% 늘렸습니다."),
                UserSource(
                    source_id=SourceId("team"), text="공통 양식을 만들고 팀 의견을 반영했습니다."
                ),
            ),
        ),
        Responses(analysis_edit=exclude_first),
    )
    assert result.outline.selected_candidate_ids == ("C2",)
    assert "900%" not in (result.outline.core_answer or "")
    assert any("900%" in f.quote for f in result.facts)


def test_team_outcome_not_personal_causality() -> None:
    result = run(request_for("제가 초안을 만들었습니다. 팀원들은 양식을 함께 사용했습니다."))
    team = next(f for f in result.facts if "팀원들" in f.quote)
    assert team.attribution == "팀"
    assert "혼자" not in (result.outline.core_answer or "")
    assert "덕분" not in (result.outline.core_answer or "")


@pytest.mark.parametrize("bad_state", ["unverified", "conflicting"])
def test_unavailable_fact_never_reaches_structure_allocation(bad_state: str) -> None:
    def hold(output: AnalysisOutput) -> AnalysisOutput:
        facts = tuple(f.model_copy(update={"information_state": bad_state}) for f in output.facts)
        links = tuple(
            link.model_copy(update={"information_state": bad_state, "use_status": "held"})
            for link in output.analysis.evidence_links
        )
        return output.model_copy(
            update={
                "facts": facts,
                "analysis": output.analysis.model_copy(update={"evidence_links": links}),
            }
        )

    result = run(request_for(), Responses(analysis_edit=hold))
    assert result.outline.core_answer is None
    assert all(not s.fact_ids for s in result.outline.sections)
    assert result.analysis.gaps


def test_held_evidence_in_model_outline_retries_then_falls_back() -> None:
    def inject(output: StructureOutput) -> StructureOutput:
        section = output.outline.sections[0].model_copy(update={"fact_ids": ("F1",)})
        return output.model_copy(
            update={
                "outline": output.outline.model_copy(
                    update={"sections": (section, *output.outline.sections[1:])}
                )
            }
        )

    responses = Responses(analysis_edit=exclude_first, structure_edit=inject)
    result = run(request_for(), responses)
    assert responses.calls.count("plan_structure") == 2
    assert all(not s.fact_ids for s in result.outline.sections)


class FailedMaterials:
    async def search_company_job_materials(
        self, company_name: str, job_title: str | None = None
    ) -> tuple[CompanyMaterial, ...]:
        _ = company_name, job_title
        raise TimeoutError

    async def writing_guide(self, question_type: str) -> str:
        _ = question_type
        raise TimeoutError

    async def writing_prompt(self, question_type: str) -> str:
        _ = question_type
        raise TimeoutError


def test_mcp_failure_still_plans() -> None:
    state = seed(request_for().model_copy(update={"company_name": "Example"}))
    result = anyio.run(execute, state, Responses(), FailedMaterials())
    assert result.analysis.research_status == "unavailable"
    assert result.outline.paragraphs
    assert all(source.metadata.origin == "user" for source in result.sources)


def test_not_applicable_optional_evidence_cannot_break_fallback() -> None:
    def optional(output: AnalysisOutput) -> AnalysisOutput:
        requirements = tuple(
            r.model_copy(update={"required_by_prompt": False}) for r in output.analysis.requirements
        )
        links = tuple(
            link.model_copy(update={"applicability": "not_applicable"})
            for link in output.analysis.evidence_links
        )
        return output.model_copy(
            update={
                "analysis": output.analysis.model_copy(
                    update={"requirements": requirements, "evidence_links": links}
                )
            }
        )

    result = run(request_for(), Responses(analysis_edit=optional, failing_stage="plan_structure"))
    assert result.outline.core_answer is None
    assert result.outline.paragraphs


def test_unparsed_requirement_stays_unassessed_even_with_model_link() -> None:
    def unparsed(output: AnalysisOutput) -> AnalysisOutput:
        requirements = tuple(
            r.model_copy(update={"resolution": "unparsed"}) for r in output.analysis.requirements
        )
        return output.model_copy(
            update={
                "analysis": output.analysis.model_copy(
                    update={"requirements": requirements, "analysis_status": "partial"}
                )
            }
        )

    result = run(request_for(), Responses(analysis_edit=unparsed))
    assert all(m.planned_coverage == "unfilled" for m in result.outline.requirement_map)
    assert result.outline.core_answer is None


def test_team_action_not_allocated_as_own_action() -> None:
    result = run(request_for("팀원들은 양식을 만들었습니다.", "본인의 행동을 설명하세요."))
    section = next(s for s in result.outline.sections if "R-action" in s.requirement_ids)
    assert section.write_mode == "omit"
    assert section.allowed_content == ""
    assert result.facts[0].attribution == "팀"
