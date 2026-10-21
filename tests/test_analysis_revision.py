import anyio

from agent.contracts import (
    EssayRequest,
    QuestionKey,
    QuestionRegistryEntry,
    QuestionUpdate,
    RevisionContext,
    SourceHistory,
    SourceId,
    UserSource,
)
from agent.stage_analysis_models import AnalysisOutput
from tests.analysis_support import Responses, execute, request_for, seed
from tests.fixtures.cases import ContractCase


def test_normalized_answer_is_snapshotted_once_and_reserved_id_cannot_collide() -> None:
    state = seed(
        EssayRequest(
            experiences=(
                UserSource(source_id=SourceId("answer-uuid"), text="기한을 지켰습니다."),
                UserSource(source_id=SourceId("field:job_posting"), text="담당했습니다."),
            ),
            job_posting_text="자료 작성 업무",
            question_updates=(
                QuestionUpdate(
                    question_key=QuestionKey("q"), response_kind="answer", text="기한을 지켰습니다."
                ),
            ),
        )
    )
    result = anyio.run(execute, state, Responses())
    assert [source.source_id for source in result.sources] == [
        "user:answer-uuid",
        "user:field:job_posting",
        "field:job_posting",
    ]
    assert sum(fact.quote == "기한을 지켰습니다." for fact in result.facts) == 1


def test_unrelated_same_detail_cannot_inherit_unavailable_or_existing_key() -> None:
    state = seed(request_for())
    state["revision_context"] = RevisionContext(
        source_history=(),
        question_registry=(
            QuestionRegistryEntry(
                question_key=QuestionKey("unrelated"),
                subject_source_ids=(SourceId("user:other"),),
                missing_detail="실제 배운 점",
                question_status="unavailable",
                user_response_source_id=None,
            ),
        ),
    )

    def spoof(output: AnalysisOutput) -> AnalysisOutput:
        gaps = tuple(
            gap.model_copy(
                update={"question_key": QuestionKey("unrelated"), "question_status": "asked"}
            )
            for gap in output.analysis.gaps
        )
        return output.model_copy(
            update={"analysis": output.analysis.model_copy(update={"gaps": gaps})}
        )

    result = anyio.run(execute, state, Responses(analysis_edit=spoof))
    gap = next(g for g in result.analysis.gaps if "R-learning" in g.requirement_ids)
    assert gap.question_key != "unrelated"
    assert gap.question_status == "proposed"


def test_unavailable_with_removed_historical_answer_does_not_reask() -> None:
    state = seed(request_for())
    state["revision_context"] = RevisionContext(
        source_history=(
            SourceHistory(
                source_id=SourceId("user:answer"),
                previous_text="배운 점은 없습니다.",
                current_text=None,
                status="removed",
                evidence_version=state["evidence_version"],
            ),
        ),
        question_registry=(
            QuestionRegistryEntry(
                question_key=QuestionKey("learning"),
                subject_source_ids=(SourceId("user:event"),),
                missing_detail="실제 배운 점",
                question_status="unavailable",
                user_response_source_id=SourceId("user:answer"),
            ),
        ),
    )
    result = anyio.run(execute, state, Responses())
    gap = next(g for g in result.analysis.gaps if "R-learning" in g.requirement_ids)
    assert gap.question_key == "learning"
    assert gap.question_status == "unavailable"
    assert gap.question is None


def test_known_question_key_preserves_unavailable_when_detail_is_paraphrased() -> None:
    state = seed(request_for())
    state["revision_context"] = RevisionContext(
        source_history=(),
        question_registry=(
            QuestionRegistryEntry(
                question_key=QuestionKey("learning"),
                subject_source_ids=(SourceId("user:event"),),
                missing_detail="배운 점",
                question_status="unavailable",
                user_response_source_id=None,
            ),
        ),
    )

    def paraphrase(output: AnalysisOutput) -> AnalysisOutput:
        gaps = tuple(
            g.model_copy(
                update={
                    "question_key": QuestionKey("learning"),
                    "missing_detail": "이 일에서 새롭게 알게 된 점",
                }
            )
            for g in output.analysis.gaps
        )
        return output.model_copy(
            update={"analysis": output.analysis.model_copy(update={"gaps": gaps})}
        )

    result = anyio.run(execute, state, Responses(analysis_edit=paraphrase))
    gap = next(g for g in result.analysis.gaps if "R-learning" in g.requirement_ids)
    assert gap.question_key == "learning"
    assert gap.question_status == "unavailable"
    assert gap.question is None


def test_generated_history_not_reextracted() -> None:
    previous = ContractCase.load("complete.json").parse().bundle
    assert previous is not None
    state = seed(EssayRequest(revision_instruction="3곳을 5곳으로 바꿔 주세요."))
    state["previous_draft"] = previous
    result = anyio.run(execute, state, Responses())
    assert result.sources == ()
    assert result.facts == ()
    assert result.outline.core_answer is None
