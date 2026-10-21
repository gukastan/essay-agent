from dataclasses import dataclass, field
from pathlib import Path

import anyio

from agent import contracts as c
from agent.deps import SupervisorDeps
from agent.essay_fake import essay_response
from agent.essay_llm import ErrorKind, GenerationError, GenerationUsage, Output, Stage
from agent.fake_llm import FastLLM, QualityLLM
from agent.graph import build_graph
from agent.stage_review_models import ReviewOutput, ReviewPayload
from tests.analysis_support import seed
from tests.composition_support import CompositionView


class FinalView(CompositionView):
    reviewed_bundle: c.DraftBundle
    review: c.Review
    best_bundle: c.DraftBundle
    best_review: c.Review
    repair_count: int = 0
    repair_log: tuple[c.RepairLogEntry, ...] = ()
    review_control: c.ReviewControl
    stop_reason: str | None
    result: c.EssayResult
    usage: tuple[GenerationUsage, ...]


@dataclass(frozen=True, slots=True)
class Cycles:
    repairs: int = 0
    failure: Stage | None = None
    unsafe: bool = False
    calls: list[Stage] = field(default_factory=list)
    payloads: list[ReviewPayload] = field(default_factory=list)

    def __call__(
        self, stage: Stage, payload: c.ContractModel, output_model: type[Output]
    ) -> Output:
        self.calls.append(stage)
        if stage == self.failure:
            raise GenerationError(ErrorKind.TIMEOUT, GenerationUsage(attempts=()))
        output = essay_response(stage, payload, output_model)
        if stage == "title_and_review":
            current = ReviewPayload.model_validate(payload.model_dump())
            self.payloads.append(current)
            review = ReviewOutput.model_validate(output.model_dump())
            if self.unsafe:
                review = review.model_copy(
                    update={
                        "sentence_checks": tuple(
                            check.model_copy(update={"status": "unsupported"})
                            for check in review.sentence_checks
                        )
                    }
                )
            remaining = max(0, self.repairs - current.repair_count)
            issues = tuple(
                c.ReviewIssue(
                    issue_id=c.IssueId(f"title-{i}"),
                    code="subtitle",
                    area="subtitle",
                    sentence_ids=(),
                    section_ids=(),
                    requirement_ids=(),
                    fact_ids=(),
                    gap_ids=(),
                    excerpt=None,
                    reason="Injected current title issue",
                    action="replace_title",
                    verification="Check the selected title",
                    fixable_without_new_info=True,
                    status="open",
                )
                for i in range(remaining)
            )
            return output_model.model_validate(
                review.model_copy(update={"issues": (*review.issues, *issues)}).model_dump()
            )
        return output


async def execute_graph(
    request: c.EssayRequest, script: Cycles
) -> tuple[FinalView, tuple[str, ...]]:
    fast, quality = FastLLM(script), QualityLLM(script)
    state = seed(request)
    trace: list[str] = []
    try:
        graph = build_graph(SupervisorDeps(fast, quality))
        async for update in graph.astream(state, {"recursion_limit": 20}, stream_mode="updates"):
            for node, patch in update.items():
                trace.append(node)
                state = {**state, **patch}
        return FinalView.model_validate(state), tuple(trace)
    finally:
        await fast.aclose()
        await quality.aclose()


def run_graph(
    request: c.EssayRequest, script: Cycles, directory: Path
) -> tuple[FinalView, tuple[str, ...]]:
    result, trace = anyio.run(execute_graph, request, script)
    directory.mkdir(parents=True, exist_ok=True)
    _ = (directory / "final.json").write_text(result.model_dump_json(indent=2))
    _ = (directory / "trace.txt").write_text("\n".join(trace))
    return result, trace
