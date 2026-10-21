import pytest

from agent.contracts import EssayRequest, LengthPolicy, ParagraphId, ParagraphPlan
from agent.stage_structure_models import StructureOutput
from tests.analysis_support import COMMON, Responses, request_for, run


def three_paragraphs(output: StructureOutput) -> StructureOutput:
    original = output.outline.paragraphs[0]
    paragraphs = tuple(
        ParagraphPlan(
            paragraph_id=ParagraphId(f"P{i}"),
            order=i,
            purpose=f"설명 초점 {i}",
            allocations=(allocation,),
            previous_relation=None,
            weight=weight,
            target_chars=999,
            budget_reason="서로 다른 요구별 비중",
        )
        for i, (allocation, weight) in enumerate(
            zip(original.allocations[:3], (25, 50, 25), strict=True)
        )
    )
    return output.model_copy(
        update={
            "outline": output.outline.model_copy(
                update={
                    "paragraphs": paragraphs,
                    "budget": output.outline.budget.model_copy(
                        update={"subtitle_reserved_chars": 16}
                    ),
                }
            )
        }
    )


@pytest.mark.parametrize(
    ("subtitle", "newlines", "body_budget"),
    [(False, True, 596), (False, False, 600), (True, True, 578)],
)
def test_budget_respects_subtitle_and_newlines(
    *, subtitle: bool, newlines: bool, body_budget: int
) -> None:
    request = request_for(COMMON, "경험의 역할과 행동과 결과와 배운 점을 설명하세요.")
    request = request.model_copy(
        update={
            "length_policy": LengthPolicy(
                max_chars=600, include_subtitle=subtitle, include_newlines=newlines
            )
        }
    )
    result = run(request, Responses(structure_edit=three_paragraphs))
    assert result.outline.budget.usable_body_chars == body_budget
    assert sum(p.target_chars or 0 for p in result.outline.paragraphs) == body_budget
    if body_budget == 596:
        assert tuple(p.target_chars for p in result.outline.paragraphs) == (149, 298, 149)


def test_tiny_limit_reports_conflict_and_continues() -> None:
    request = EssayRequest(length_policy=LengthPolicy(max_chars=1, include_subtitle=True))
    result = run(request)
    assert result.outline.paragraphs
    assert any("constraint_conflict" in note for note in result.outline.budget.constraint_notes)
