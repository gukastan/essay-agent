from dataclasses import dataclass, field
from pathlib import Path
from typing import Final

import anyio
import pytest

from agent.contracts import ContractModel, EssayRequest, VersionId
from agent.deps import SupervisorDeps
from agent.essay_fake import essay_response
from agent.essay_llm import Output, Stage
from agent.essay_prompts import build_prompt
from agent.fake_llm import FastLLM, QualityLLM
from agent.graph import build_graph
from agent.previous_draft import PreviousDraft
from agent.stage_integration_models import IntegrationPayload
from agent.stage_writing_models import WritingPayload
from tests.analysis_support import seed
from tests.review_graph_support import FinalView

OLD_CLAIM: Final = "제가 987654건을 달성하여 매출을 876543% 높였습니다."


@dataclass(frozen=True, slots=True)
class Capture:
    """Record immutable payloads for boundary assertions."""

    calls: list[tuple[Stage, ContractModel]] = field(default_factory=list)

    def __call__(self, stage: Stage, payload: ContractModel, output_model: type[Output]) -> Output:
        self.calls.append((stage, payload))
        return essay_response(stage, payload, output_model)


@pytest.mark.parametrize("has_parent", [False, True])
def test_previous_wording_is_editing_only_without_evidence_promotion(*, has_parent: bool) -> None:
    request = EssayRequest(revision_instruction="더 간결하게 수정해 주세요.")
    previous = PreviousDraft(
        document_id=request.document_id,
        version_id=VersionId("stored-parent"),
        subtitle="이전 제목",
        body=OLD_CLAIM,
    )
    capture = Capture()

    async def run() -> FinalView:
        state = seed(request)
        if has_parent:
            state["previous_draft"] = previous
        fast, quality = FastLLM(capture), QualityLLM(capture)
        try:
            result = await build_graph(SupervisorDeps(fast, quality)).ainvoke(
                state, {"recursion_limit": 20}
            )
            return FinalView.model_validate(result)
        finally:
            await fast.aclose()
            await quality.aclose()

    final = anyio.run(run)
    assert final.sources == ()
    assert final.facts == ()
    assert OLD_CLAIM not in final.result.body
    assert "987654" not in final.result.copy_text
    assert final.result.personalization == "non_personalized"
    assert final.result.body
    assert final.result.subtitle
    writing = [payload for stage, payload in capture.calls if stage == "write_sections"]
    integration = [payload for stage, payload in capture.calls if stage == "integrate_draft"]
    assert len(writing) == len(integration) == 1
    assert WritingPayload.model_validate(writing[0]).previous_draft == (
        previous if has_parent else None
    )
    assert IntegrationPayload.model_validate(integration[0]).previous_draft == (
        previous if has_parent else None
    )
    for stage, payload in capture.calls:
        if stage not in ("write_sections", "integrate_draft"):
            assert "previous_draft" not in payload.model_dump()
            assert OLD_CLAIM not in payload.model_dump_json()
    editing: tuple[tuple[Stage, ContractModel], ...] = (
        ("write_sections", writing[0]),
        ("integrate_draft", integration[0]),
    )
    for stage, payload in editing:
        prompt = build_prompt(stage, payload)
        assert "previous_draft" in prompt.system
        assert "허용 facts" in prompt.system
    directory = Path("../.omo/evidence/essay-agent/task-7-previous-draft")
    directory.mkdir(parents=True, exist_ok=True)
    _ = (directory / f"result-{has_parent}.json").write_text(final.model_dump_json(indent=2))
    _ = (directory / f"payloads-{has_parent}.json").write_text(
        "[\n" + ",\n".join(p.model_dump_json() for _, p in capture.calls) + "\n]"
    )
