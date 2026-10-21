import sys
from pathlib import Path
from typing import Self
from uuid import uuid4

import anyio
import pytest
from pydantic import model_validator

from agent import contracts as c
from agent.api_models import ChatResponse
from agent.contracts import ContractViolation
from agent.essay_llm import GenerationError, Stage
from agent.essay_prompts import build_prompt
from agent.session_store import SqliteSessionStore
from agent.stage_analysis_models import PayloadValidationInfo
from tests.e2e_diagnostics import DiagnosticLLM, trace
from tests.e2e_processes import record, running
from tests.llm_support import FactOutput, SuppliedFacts, completion, provider


def test_common_prompt_localizes_semantic_fields_without_changing_source_data() -> None:
    payload = SuppliedFacts(facts=("Original source QUOTE / ID-123",))
    prompt = build_prompt("analyze_context", payload)
    assert "판정 이유·검토·제안·질문·안내)은 한국어로" in prompt.system
    assert "ID와 enum 값" in prompt.system
    assert "원문 직접 인용은 그대로 보존" in prompt.system
    assert "Original source QUOTE / ID-123" in prompt.user
    assert "요구마다 해당 연결 또는 명시적 gap" in prompt.system
    assert '"information_state":"available"' in prompt.system
    assert "Fact.claim_kind=stated_view" in prompt.system
    assert "과거 질문·missing_detail은 당시의 이력" in prompt.system
    assert "현재 근거 판단을 대신하지 않는다" in prompt.system
    assert "gap이 있어도 분석은 complete일 수 있다" in prompt.system
    assert "본문을 자기소개서의 정의나 작성 요령으로 대체하지 않는다" in prompt.system
    assert "예시는 사용자의 경험이나 신념이 아니며" in prompt.system


@pytest.mark.parametrize(
    ("stage", "required"),
    [
        ("analyze_context", "각각 별도 requirement_id로 분해"),
        ("write_sections", "배움 gap을 자연스러운 마무리로 메우지 않는다"),
        ("title_and_review", "해당 생각의 직접 진술이 없으면 unsupported"),
        ("write_sections", "행동만으로 의도·대상·영향을 보충하지 않는다"),
        ("title_and_review", "목적이나 효과를 덧붙이면 unsupported로 판정"),
    ],
)
def test_personal_learning_requires_explicit_source(stage: Stage, required: str) -> None:
    prompt = build_prompt(stage, SuppliedFacts(facts=()))
    assert required in prompt.system


def test_opt_in_capture_contains_only_validated_output(tmp_path: Path) -> None:
    destination = tmp_path / "diagnostic.jsonl"

    async def run() -> None:
        async with provider((completion('{"facts":[],"note":null}'),)) as harness:
            wrapper = DiagnosticLLM(harness.adapter, destination, capture=True)
            result = await wrapper.generate("analyze_context", SuppliedFacts(facts=()), FactOutput)
            captured = tuple(destination.with_suffix(".validated").glob("*.json"))
            assert len(captured) == 1
            assert FactOutput.model_validate_json(captured[0].read_text()) == result.output

    anyio.run(run)


class RejectedFacts(FactOutput):
    @model_validator(mode="after")
    def reject(self, info: PayloadValidationInfo) -> Self:
        if info.context is not None:
            code = "diagnostic_rejection"
            raise ContractViolation(code, "private exception detail")
        return self


def test_diagnostics_record_only_safe_metadata(tmp_path: Path) -> None:
    path = tmp_path / "diagnostic.jsonl"

    async def run() -> None:
        reply = completion('{"facts":[],"note":"private provider content"}')
        async with provider((reply, reply)) as harness:
            wrapper = DiagnosticLLM(harness.adapter, path)
            original = sys.gettrace()
            sys.settrace(trace)
            try:
                with pytest.raises(GenerationError):
                    _ = await wrapper.generate(
                        "analyze_context", SuppliedFacts(facts=("private source",)), RejectedFacts
                    )
            finally:
                sys.settrace(original)

    anyio.run(run)
    captured = path.read_text()
    assert "diagnostic_rejection" in captured
    assert '"kind": "format"' in captured
    assert '"input_tokens": 11' in captured
    assert "private" not in captured
    destination = Path("../.omo/evidence/essay-agent/task-10-safe-diagnostic.jsonl")
    destination.parent.mkdir(parents=True, exist_ok=True)
    _ = destination.write_text(captured)


def test_real_process_unavailable_style_and_explicit_source_correction(tmp_path: Path) -> None:
    database = tmp_path / "revision.db"
    form = c.EssayRequest.model_validate_json(
        Path("tests/fixtures/sparse_request.json").read_text()
    ).model_copy(update={"question": "협업 경험과 배운 점을 설명해 주세요."})
    with running(database, "questions", "revision-before") as stack:
        reply = stack.client.post("/chat", content=form.model_dump_json())
        first = ChatResponse.model_validate_json(reply.text).result
        question = next(item for item in first.suggestions if item.example_question is not None)
        assert question.question_key is not None
        unavailable = form.model_copy(
            update={
                "request_id": uuid4(),
                "parent_version_id": first.version_id,
                "question_updates": (
                    c.QuestionUpdate(
                        question_key=question.question_key, response_kind="unavailable", text=None
                    ),
                ),
            }
        )
        second = ChatResponse.model_validate_json(
            stack.client.post("/chat", content=unavailable.model_dump_json()).text
        ).result
        style = unavailable.model_copy(
            update={
                "request_id": uuid4(),
                "parent_version_id": second.version_id,
                "question_updates": (),
                "revision_instruction": "담백한 문체로 다듬어 주세요.",
            }
        )
        reply = stack.client.post("/chat", content=style.model_dump_json())
        record("task-10-revision-style.txt", reply)
        third = ChatResponse.model_validate_json(reply.text).result
        assert all(
            item.example_question is None
            for item in third.suggestions
            if item.question_key == question.question_key
        )
    corrected = style.model_copy(
        update={
            "request_id": uuid4(),
            "parent_version_id": third.version_id,
            "experiences": (
                form.experiences[0].model_copy(
                    update={
                        "text": form.experiences[0].text
                        + " 이를 통해 분류 기준을 먼저 합의해야 한다는 점을 배웠습니다."
                    }
                ),
            ),
        }
    )
    with running(database, "resolved", "revision-after") as stack:
        reply = stack.client.post("/chat", content=corrected.model_dump_json())
        record("task-10-revision-corrected.txt", reply)
        assert reply.status_code == 200
        final = ChatResponse.model_validate_json(reply.text).result
        assert "배웠습니다" in final.body
        assert tuple(stack.directory.glob("*-analyze_context-payload.json"))
    store = SqliteSessionStore(database)
    try:
        saved = store.get(corrected.request_id)
        assert saved is not None
        matching = next(
            item
            for item in saved.revision_context.question_registry
            if item.question_key == question.question_key
        )
        assert matching.question_status == "resolved"
        assert saved.revision_context.source_history
        assert saved.result == final
    finally:
        store.close()
