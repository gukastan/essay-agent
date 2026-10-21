import pytest

from agent.contract_base import QuestionStatus
from agent.contracts import QuestionRegistryEntry, RevisionContext
from agent.graph_state import EssayState
from agent.revision_registry import final_revision
from tests.fixtures.cases import ContractCase


@pytest.mark.parametrize(
    ("prior_status", "current_status", "expected"),
    [
        (None, "proposed", "proposed"),
        ("asked", "proposed", "asked"),
        ("unavailable", "resolved", "resolved"),
        ("unavailable", "proposed", "unavailable"),
    ],
)
def test_question_status_requires_interaction_or_current_resolution(
    prior_status: QuestionStatus | None,
    current_status: QuestionStatus,
    expected: QuestionStatus,
) -> None:
    context = ContractCase.load("suggestions.json").parse()
    assert context.analysis is not None
    assert context.result is not None
    assert context.request is not None
    gap = context.analysis.gaps[0].model_copy(update={"question_status": current_status})
    suggestion = context.result.suggestions[0].model_copy(
        update={"question_key": gap.question_key, "example_question": "추가 설명이 있나요?"}
    )
    registry = (
        ()
        if prior_status is None
        else (
            QuestionRegistryEntry(
                question_key=gap.question_key,
                subject_source_ids=(),
                missing_detail=gap.missing_detail,
                question_status=prior_status,
                user_response_source_id=None,
            ),
        )
    )
    state = EssayState(
        request=context.request,
        evidence_version=context.evidence_version,
        revision_context=RevisionContext(question_registry=registry, source_history=()),
        analysis=context.analysis.model_copy(update={"gaps": (gap,)}),
        result=context.result.model_copy(update={"suggestions": (suggestion,)}),
        sources=context.sources,
        facts=context.facts,
    )
    assert final_revision(state).question_registry[0].question_status == expected
