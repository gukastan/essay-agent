import time
from dataclasses import dataclass, field

import anyio
import pytest

from agent.contracts import EssayRequest, SourceId, UserSource
from agent.deps import SupervisorDeps
from agent.fake_llm import FastLLM, QualityLLM
from agent.graph import build_graph
from agent.mcp_materials import CompanyMaterial
from tests.analysis_support import Responses, execute, request_for, seed


@dataclass(frozen=True, slots=True)
class SlowMaterials:
    calls: list[str] = field(default_factory=list)

    async def search_company_job_materials(
        self, company_name: str, job_title: str | None = None
    ) -> tuple[CompanyMaterial, ...]:
        self.calls.append(company_name)
        _ = job_title
        await anyio.sleep_forever()
        return ()

    async def writing_guide(self, question_type: str) -> str:
        _ = question_type
        return ""

    async def writing_prompt(self, question_type: str) -> str:
        _ = question_type
        return ""


@pytest.mark.parametrize(
    "essay_request",
    [
        EssayRequest(),
        EssayRequest(
            company_name="Company",
            company_sources=(
                UserSource(source_id=SourceId("provided"), text="사용자 제공 기업 자료"),
            ),
        ),
    ],
)
def test_user_material_priority_and_no_company_skip_lookup(essay_request: EssayRequest) -> None:
    materials = SlowMaterials()
    result = anyio.run(execute, seed(essay_request), Responses(), materials)
    assert materials.calls == []
    assert result.analysis.research_status == "not_requested"
    assert result.outline.paragraphs


def test_total_research_deadline_is_fifteen_seconds_and_never_retries() -> None:
    materials = SlowMaterials()
    state = seed(request_for().model_copy(update={"company_name": "Company"}))
    started = time.monotonic()
    result = anyio.run(execute, state, Responses(), materials)
    elapsed = time.monotonic() - started
    assert 14.8 <= elapsed < 18
    assert materials.calls == ["Company"]
    assert result.analysis.research_status == "unavailable"
    assert result.outline.paragraphs


def test_installed_stategraph_streams_two_nodes_in_order_with_fixed_analysis() -> None:
    async def scenario() -> None:
        responses = Responses()
        fast, quality = FastLLM(responses), QualityLLM(responses)
        try:
            graph = build_graph(SupervisorDeps(fast, quality))
            updates = [
                update
                async for update in graph.astream(
                    seed(request_for()), {"recursion_limit": 20}, stream_mode="updates"
                )
            ]
            assert [tuple(update) for update in updates] == [
                ("analyze_context",),
                ("plan_structure",),
            ]
            assert "sources" in updates[0]["analyze_context"]
            assert "analysis" in updates[0]["analyze_context"]
            assert "analysis" not in updates[1]["plan_structure"]
            assert "sources" not in updates[1]["plan_structure"]
            assert "outline" in updates[1]["plan_structure"]
            assert responses.calls == ["analyze_context", "plan_structure"]
        finally:
            await fast.aclose()
            await quality.aclose()

    anyio.run(scenario)
