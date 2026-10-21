from pathlib import Path

import anyio

from agent.contracts import (
    DraftBundle,
    EssayRequest,
    IntegrationReport,
    SectionDraft,
    Sentence,
    WritingReport,
)
from agent.deps import SupervisorDeps
from agent.fake_llm import FastLLM, QualityLLM
from agent.graph import build_graph
from tests.analysis_support import Responses, RunView, seed


class CompositionView(RunView):
    fallback_provenance: tuple[Sentence, ...]
    section_drafts: tuple[SectionDraft, ...]
    writing_report: WritingReport
    candidate_bundle: DraftBundle
    integration_report: IntegrationReport


async def execute_composition(request: EssayRequest, responses: Responses) -> CompositionView:
    fast, quality = FastLLM(responses), QualityLLM(responses)
    try:
        graph = build_graph(SupervisorDeps(fast, quality), stop_after="integrate_draft")
        result = await graph.ainvoke(seed(request), {"recursion_limit": 20})
        return CompositionView.model_validate(result)
    finally:
        await fast.aclose()
        await quality.aclose()


def run_composition(
    request: EssayRequest,
    directory: Path,
    responses: Responses | None = None,
) -> tuple[CompositionView, Responses]:
    script = responses or Responses()
    result = anyio.run(execute_composition, request, script)
    directory.mkdir(parents=True, exist_ok=True)
    _ = (directory / "composition.json").write_text(result.model_dump_json(indent=2))
    return result, script
