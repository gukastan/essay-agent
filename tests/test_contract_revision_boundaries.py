"""Question history may retain removed answers without reactivating them as facts."""

import pytest

from agent.contracts import (
    ContractContext,
    ContractViolation,
    EvidenceVersion,
    Fact,
    FactId,
    QuestionKey,
    QuestionRegistryEntry,
    RevisionContext,
    SourceHistory,
    SourceId,
    SourceSpan,
    validate_contract,
)


def historical_context(response_id: SourceId) -> ContractContext:
    version = EvidenceVersion("current-evidence")
    source_id = SourceId("answer:Q-1")
    return ContractContext(
        evidence_version=version,
        revision_context=RevisionContext(
            source_history=(
                SourceHistory(
                    source_id=source_id,
                    previous_text="팀 의견을 반영했습니다.",
                    current_text=None,
                    status="removed",
                    evidence_version=version,
                ),
            ),
            question_registry=(
                QuestionRegistryEntry(
                    question_key=QuestionKey("Q-1"),
                    subject_source_ids=(source_id,),
                    missing_detail="협업 행동",
                    question_status="unavailable",
                    user_response_source_id=response_id,
                ),
            ),
        ),
    )


def test_removed_historical_response_link_is_preserved() -> None:
    context = historical_context(SourceId("answer:Q-1"))
    validate_contract(context)
    restored = ContractContext.model_validate_json(context.model_dump_json())
    validate_contract(restored)
    assert restored == context
    assert restored.sources == ()
    assert restored.facts == ()


def test_unknown_historical_response_is_rejected() -> None:
    context = historical_context(SourceId("answer:missing"))
    with pytest.raises(ContractViolation) as caught:
        validate_contract(context)
    assert caught.value.code == "unknown_reference"
    assert caught.value.detail == "question.response_source"


def test_historical_source_cannot_support_current_fact() -> None:
    context = historical_context(SourceId("answer:Q-1"))
    fact = Fact(
        fact_id=FactId("F-1"),
        source_id=SourceId("answer:Q-1"),
        source_kind="applicant",
        quote="팀 의견을 반영했습니다.",
        span=SourceSpan(start=0, end=13),
        experience_id=None,
        claim_kind="personal_event",
        attribution="user",
        information_state="available",
        conflict_ids=(),
    )
    current = context.model_copy(update={"facts": (fact,)})
    with pytest.raises(ContractViolation) as caught:
        validate_contract(current)
    assert caught.value.code == "unknown_reference"
    assert caught.value.detail == "fact.source_id"
