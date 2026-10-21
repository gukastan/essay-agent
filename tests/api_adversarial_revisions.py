from pathlib import Path
from typing import Literal
from uuid import uuid4

from agent import contracts as c
from agent.api_models import RunLookup
from agent.stage_analysis_models import AnalysisPayload
from agent.stage_writing_models import WritingPayload
from tests.api_adversarial_support import complete, lookup_input, record_model, request, session


async def check_revision_history(
    tmp_path: Path,
    correction: Literal["still_missing", "now_supported"],
) -> None:
    # Given a displayed missing-learning question and its persisted raw applicant source.
    async with session(tmp_path, mode="resolved") as current:
        prefix = f"history-{correction}"
        form = request()
        initial = (await complete(current, form, f"{prefix}-initial")).result
        question = next(s for s in initial.suggestions if s.example_question is not None)
        assert question.question_key is not None
        first_record = current.store.get(form.request_id)
        assert first_record is not None
        record_model(f"history-first-{correction}", first_record)
        assert first_record.revision_context.question_registry[0].question_status == "proposed"
        unavailable = form.model_copy(
            update={
                "request_id": uuid4(),
                "parent_version_id": initial.version_id,
                "question_updates": (
                    c.QuestionUpdate(
                        question_key=question.question_key,
                        response_kind="unavailable",
                        text=None,
                    ),
                ),
            }
        )
        second = (await complete(current, unavailable, f"{prefix}-unavailable")).result
        # When only style changes, then prior unavailable status still suppresses reasking.
        style = unavailable.model_copy(
            update={
                "request_id": uuid4(),
                "parent_version_id": second.version_id,
                "question_updates": (),
                "revision_instruction": "문장을 차분하게 다듬어 주세요.",
            }
        )
        third = (await complete(current, style, f"{prefix}-style")).result
        for result in (second, third):
            matching = [s for s in result.suggestions if s.question_key == question.question_key]
            assert matching
            assert all(s.question_status == "unavailable" for s in matching)
            assert all(s.example_question is None for s in matching)
        # When a user corrects the same source ID, then only new text is active evidence.
        corrected_text = (
            "가상 도서관에서 반납함의 분류표를 정리했습니다."
            if correction == "still_missing"
            else "가상 도서관에서 안내표를 정리하며 분류 기준 합의의 중요성을 배웠습니다."
        )
        corrected = style.model_copy(
            update={
                "request_id": uuid4(),
                "parent_version_id": third.version_id,
                "experiences": (form.experiences[0].model_copy(update={"text": corrected_text}),),
            }
        )
        final = (await complete(current, corrected, f"{prefix}-corrected")).result
        assert corrected_text in final.body
        assert form.experiences[0].text not in final.body
        saved = current.store.get(corrected.request_id)
        assert saved is not None
        history = [
            h
            for h in saved.revision_context.source_history
            if h.source_id == "user:fictional-library"
        ]
        assert history[-1].status == "superseded"
        assert history[-1].previous_text == form.experiences[0].text
        assert history[-1].current_text == corrected_text
        record_model(f"history-record-{correction}", saved)
        assert saved.revision_context.question_registry[0].question_status == (
            "unavailable" if correction == "still_missing" else "resolved"
        )
        restored = await lookup_input(current, corrected.request_id, f"{prefix}-get")
        assert restored.experiences == corrected.experiences
        assert restored.experiences[0].source_id == "fictional-library"
        original_lookup = await current.client.get(f"/runs/{form.request_id}")
        assert RunLookup.model_validate_json(original_lookup.text).result == initial
        analysis = [p for p in current.responses.payloads if isinstance(p, AnalysisPayload)][-1]
        assert [s.text for s in analysis.sources if s.source_kind == "applicant"] == [
            corrected_text
        ]
        writing = [p for p in current.responses.payloads if isinstance(p, WritingPayload)][-1]
        assert writing.previous_draft is not None
        assert writing.previous_draft.body == third.body
        assert all(f.quote == corrected_text for f in writing.facts if f.source_kind == "applicant")
        assert len(current.responses.calls) == 20
        if correction == "now_supported":
            assert any(
                link.requirement_id == "R-learning" and link.fact_ids
                for link in writing.analysis.evidence_links
            )
            assert any(g.question_status == "resolved" for g in writing.analysis.gaps)
            assert not any(s.question_key == question.question_key for s in final.suggestions)


async def check_answer_identity(tmp_path: Path) -> None:
    # Given a saved optional question that receives an explicit fictional user answer.
    async with session(tmp_path) as current:
        form = request()
        initial = (await complete(current, form, "answer-initial")).result
        question = next(s for s in initial.suggestions if s.example_question is not None)
        assert question.question_key is not None
        answer = "분류 기준을 먼저 합의해야 한다는 점을 배웠습니다."
        revision = form.model_copy(
            update={
                "request_id": uuid4(),
                "parent_version_id": initial.version_id,
                "question_updates": (
                    c.QuestionUpdate(
                        question_key=question.question_key,
                        response_kind="answer",
                        text=answer,
                    ),
                ),
            }
        )
        answered = (await complete(current, revision, "answer-added")).result
        restored = await lookup_input(current, revision.request_id, "answer-get")
        sources = [s for s in restored.experiences if s.text == answer]
        assert len(sources) == 1
        assert not sources[0].source_id.startswith("user:")
        answered_record = current.store.get(revision.request_id)
        assert answered_record is not None
        entry = answered_record.revision_context.question_registry[0]
        assert entry.question_status == "asked"
        assert entry.user_response_source_id == f"user:{sources[0].source_id}"
        record_model("answer-record", answered_record)
        # When the same answer is resubmitted with a style revision, then its raw ID stays unique.
        repeated = restored.model_copy(
            update={
                "request_id": uuid4(),
                "parent_version_id": answered.version_id,
                "revision_instruction": "담백한 문체로 유지해 주세요.",
            }
        )
        result = (await complete(current, repeated, "answer-repeated")).result
        after = await lookup_input(current, repeated.request_id, "answer-repeat-get")
        assert [s for s in after.experiences if s.text == answer] == sources
        assert len(after.experiences) == 2
        assert answer in result.body
        analysis = [p for p in current.responses.payloads if isinstance(p, AnalysisPayload)][-1]
        assert [s.source_id for s in analysis.sources if s.text == answer] == [
            f"user:{sources[0].source_id}"
        ]
        assert len(current.responses.calls) == 15
