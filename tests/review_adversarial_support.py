from dataclasses import dataclass, field
from pathlib import Path
from typing import assert_never

import anyio

from agent import contracts as c
from agent import graph
from agent.deps import SupervisorDeps
from agent.essay_fake import essay_response
from agent.essay_llm import ErrorKind, GenerationError, GenerationUsage, Output, Stage, TokenUsage
from agent.fake_llm import FastLLM, QualityLLM
from agent.stage_review_models import RepairOutput, RepairPayload, ReviewOutput, ReviewPayload
from agent.stage_writing_models import WritingOutput
from tests.review_adversarial_contracts import Scenario
from tests.review_adversarial_responses import repair_output, review_output
from tests.writing_boundary_support import context_for


@dataclass(frozen=True, slots=True)
class ScriptedReview:
    scenario: Scenario
    context: c.ContractContext
    calls: list[Stage] = field(default_factory=list)
    payloads: list[ReviewPayload | RepairPayload] = field(default_factory=list)
    outputs: list[ReviewOutput | RepairOutput] = field(default_factory=list)

    def __call__(
        self, stage: Stage, payload: c.ContractModel, output_model: type[Output]
    ) -> Output:
        match stage:
            case "write_sections":
                drafts = self.context.section_drafts
                if self.scenario in ("title_only", "omitted"):
                    drafts = tuple(
                        d.model_copy(update={"allocations": ()})
                        if d.section_id == "section-result"
                        else d
                        for d in drafts
                    )
                return output_model.model_validate(
                    WritingOutput(
                        section_drafts=drafts,
                        notes=(),
                        section_checks=(),
                        personalization="partial",
                    ).model_dump()
                )
            case "integrate_draft":
                return essay_response(stage, payload, output_model)
            case "title_and_review" | "repair_draft":
                self.calls.append(stage)
                parsed = (
                    RepairPayload.model_validate(payload.model_dump())
                    if stage == "repair_draft"
                    else (ReviewPayload.model_validate(payload.model_dump()))
                )
                self.payloads.append(parsed)
                if (self.scenario == "review_error" and stage == "title_and_review") or (
                    self.scenario == "repair_error" and stage == "repair_draft"
                ):
                    raise GenerationError(
                        ErrorKind.TIMEOUT,
                        GenerationUsage(
                            attempts=(
                                TokenUsage(
                                    model="fake:timeout",
                                    input_tokens=None,
                                    output_tokens=None,
                                    total_tokens=None,
                                ),
                            )
                        ),
                    )
                output = (
                    repair_output(parsed, self.scenario)
                    if isinstance(parsed, RepairPayload)
                    else (review_output(parsed, self.scenario))
                )
                self.outputs.append(output)
                return output_model.model_validate(output.model_dump())
            case "analyze_context" | "plan_structure" | "deliver_result":
                raise AssertionError(stage)
            case _:
                assert_never(stage)


class ReviewReceipt(c.ContractModel):
    context: c.ContractContext
    initial: c.DraftBundle
    selected: c.DraftBundle
    review: c.Review
    result: c.EssayResult
    repair_count: int
    repair_log: tuple[c.RepairLogEntry, ...]
    calls: tuple[str, ...]
    trace: tuple[str, ...]
    payloads: tuple[ReviewPayload | RepairPayload, ...]
    outputs: tuple[ReviewOutput | RepairOutput, ...]


def current_context(scenario: Scenario) -> c.ContractContext:
    ctx = context_for(
        "missing" if scenario in ("missing", "unavailable", "resolved") else "omitted"
    )
    assert ctx.request is not None
    if scenario in ("lost_learning", "unsafe_swap"):
        ctx = ctx.model_copy(
            update={
                "request": ctx.request.model_copy(
                    update={
                        "length_policy": ctx.request.length_policy.model_copy(
                            update={"max_chars": 100 if scenario == "lost_learning" else 125}
                        )
                    }
                )
            }
        )
    if scenario in ("unavailable", "resolved"):
        assert ctx.analysis is not None
        ctx = ctx.model_copy(
            update={
                "analysis": ctx.analysis.model_copy(
                    update={
                        "gaps": tuple(
                            gap.model_copy(update={"question_status": scenario})
                            for gap in ctx.analysis.gaps
                        )
                    }
                )
            }
        )
    return ctx


async def execute(scenario: Scenario) -> ReviewReceipt:
    ctx = current_context(scenario)
    assert ctx.request is not None
    assert ctx.analysis is not None
    assert ctx.outline is not None
    script = ScriptedReview(scenario, ctx)
    fast, quality = FastLLM(script), QualityLLM(script)
    deps = SupervisorDeps(fast, quality)
    state: graph.EssayState = graph.EssayState(
        request=ctx.request,
        evidence_version=ctx.evidence_version,
        revision_context=c.RevisionContext(source_history=(), question_registry=()),
        sources=ctx.sources,
        facts=ctx.facts,
        analysis=ctx.analysis,
        outline=ctx.outline,
    )
    trace: list[str] = []
    snapshot = ctx.model_dump_json()
    try:
        state = {**state, **await graph.write_sections(state, deps)}
        state = {**state, **await graph.integrate_draft(state, deps)}
        assert "candidate_bundle" in state
        initial = state["candidate_bundle"]
        for _ in range(3):
            trace.append("title_and_review")
            state = {**state, **await graph.title_and_review(state, deps)}
            assert "review_control" in state
            if state["review_control"].stop:
                break
            trace.append("repair_draft")
            state = {**state, **await graph.repair_draft(state, deps)}
        assert "best_bundle" in state
        assert "best_review" in state
        if scenario in ("stale_best", "stale_all"):
            state["best_review"] = state["best_review"].model_copy(
                update={"version_id": c.VersionId("stale")}
            )
            if scenario == "stale_all":
                assert "review" in state
                state["review"] = state["review"].model_copy(
                    update={"version_id": c.VersionId("also-stale")}
                )
        before_delivery = len(script.calls)
        trace.append("deliver_result")
        state = {**state, **await graph.deliver_result(state, deps)}
        assert len(script.calls) == before_delivery
    finally:
        await fast.aclose()
        await quality.aclose()
    assert ctx.model_dump_json() == snapshot
    assert "result" in state
    assert "best_bundle" in state
    assert "best_review" in state
    result, selected, review = state["result"], state["best_bundle"], state["best_review"]
    return ReviewReceipt(
        context=ctx,
        initial=initial,
        selected=selected,
        review=review,
        result=result,
        repair_count=state.get("repair_count", 0),
        repair_log=state.get("repair_log", ()),
        calls=tuple(script.calls),
        trace=tuple(trace),
        payloads=tuple(script.payloads),
        outputs=tuple(script.outputs),
    )


def run_case(scenario: Scenario, directory: Path) -> ReviewReceipt:
    receipt = anyio.run(execute, scenario)
    _ = (directory / (scenario + ".json")).write_text(receipt.model_dump_json(indent=2))
    assert receipt.result.body.strip()
    assert receipt.result.version_id == receipt.selected.version_id == receipt.review.version_id
    assert receipt.result.quality_report.length_check.version_id == receipt.result.version_id
    assert receipt.result.body == c.render_body(receipt.selected)
    assert receipt.result.copy_text == c.render_copy_text(receipt.selected)
    assert all(entry.outcome != "pending_review" for entry in receipt.repair_log)
    return receipt
