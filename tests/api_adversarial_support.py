from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal
from uuid import UUID

import httpx
from pydantic import JsonValue, TypeAdapter
from typing_extensions import override

from agent import contracts as c
from agent.api_models import ChatResponse, RunLookup
from agent.app_runtime import AppSettings, RuntimeFactories
from agent.essay_fake import essay_response
from agent.essay_llm import Output, Stage
from agent.fake_llm import FastLLM, QualityLLM
from agent.session_store import SqliteSessionStore
from agent.stage_analysis_models import AnalysisOutput, AnalysisPayload
from agent.store_models import RunRecord, StoreUnavailableError
from server import create_app

Fault = Literal["none", "failed", "unknown", "committed", "workflow"]
AnalysisMode = Literal["questions", "resolved"]
FORM_FIELDS = {
    "request_id",
    "thread_id",
    "document_id",
    "parent_version_id",
    "company_name",
    "job_title",
    "question",
    "experiences",
    "user_views",
    "job_posting_text",
    "company_sources",
    "tone",
    "length_policy",
    "revision_instruction",
    "question_updates",
}


@dataclass(frozen=True, slots=True)
class RecordingResponses:
    mode: AnalysisMode = "questions"
    calls: list[Stage] = field(default_factory=list)
    payloads: list[c.ContractModel] = field(default_factory=list)

    def __call__(
        self, stage: Stage, payload: c.ContractModel, output_model: type[Output]
    ) -> Output:
        self.calls.append(stage)
        self.payloads.append(payload)
        output = essay_response(stage, payload, output_model)
        if isinstance(output, AnalysisOutput):
            parsed = AnalysisPayload.model_validate(payload)
            analysis = analysis_questions(output, parsed, self.mode)
            output = output_model.model_validate(analysis.model_dump())
        return output


def analysis_questions(
    output: AnalysisOutput, payload: AnalysisPayload, mode: AnalysisMode
) -> AnalysisOutput:
    gaps = tuple(
        gap.model_copy(update={"question": f"{gap.missing_detail}을 알려 주시겠어요?"})
        for gap in output.analysis.gaps
    )
    prior = payload.revision_context.question_registry
    if mode == "resolved" and prior and not gaps:
        entry = prior[0]
        gaps = (
            c.Gap(
                gap_id=c.GapId("G-R-learning"),
                question_key=entry.question_key,
                requirement_ids=(c.RequirementId("R-learning"),),
                candidate_id=None,
                missing_detail=entry.missing_detail,
                why_it_matters="현재 원문의 배운 점을 확인합니다.",
                priority=1,
                question=None,
                question_status="resolved",
            ),
        )
    return output.model_copy(update={"analysis": output.analysis.model_copy(update={"gaps": gaps})})


class FaultStore(SqliteSessionStore):
    def __init__(self, path: Path, fault: Fault) -> None:
        super().__init__(path)
        self.fault: Fault = fault
        self.attempted: list[c.EssayResult] = []

    @override
    def save_result(
        self, record: RunRecord, result: c.EssayResult, revision: c.RevisionContext
    ) -> None:
        self.attempted.append(result)
        if self.fault in ("none", "workflow", "committed"):
            super().save_result(record, result, revision)
        if self.fault in ("failed", "unknown", "committed"):
            raise StoreUnavailableError

    @override
    def get(self, request_id: UUID) -> RunRecord | None:
        if self.fault == "unknown" and self.attempted:
            raise StoreUnavailableError
        return super().get(request_id)

    @override
    def parent(self, request: c.EssayRequest) -> RunRecord | None:
        if self.fault == "workflow":
            raise StoreUnavailableError
        return super().parent(request)


@dataclass(frozen=True, slots=True)
class Session:
    client: httpx.AsyncClient
    responses: RecordingResponses
    store: FaultStore


@asynccontextmanager
async def session(
    directory: Path, fault: Fault = "none", mode: AnalysisMode = "questions"
) -> AsyncGenerator[Session]:
    responses = RecordingResponses(mode)
    stores: list[FaultStore] = []

    def make_store(path: Path) -> SqliteSessionStore:
        store = FaultStore(path, fault)
        stores.append(store)
        return store

    settings = AppSettings(backend="fake", db_path=directory / "runs.db", mcp_enabled=False)
    factories = RuntimeFactories(
        fast=lambda _: FastLLM(responses),
        quality=lambda _: QualityLLM(responses),
        store=make_store,
    )
    app = create_app(settings, factories)
    async with (
        app.router.lifespan_context(app),
        httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client,
    ):
        yield Session(client, responses, stores[0])


def request() -> c.EssayRequest:
    return c.EssayRequest(
        question="경험과 배운 점을 설명해 주세요.",
        experiences=(
            c.UserSource(
                source_id=c.SourceId("fictional-library"),
                text="가상 도서관에서 서가 안내표를 정리했습니다.",
            ),
        ),
    )


def events(response: httpx.Response) -> tuple[c.ProgressEvent, ...]:
    assert response.status_code == 200
    rows = [line[6:] for line in response.text.splitlines() if line.startswith("data: ")]
    assert rows[-1] == "[DONE]"
    assert rows.count("[DONE]") == 1
    adapter = TypeAdapter(c.ProgressEvent)
    parsed = tuple(adapter.validate_json(row) for row in rows[:-1])
    assert sum(isinstance(event, (c.FinalResult, c.RunError)) for event in parsed) == 1
    return parsed


def record(name: str, session: Session, *responses: httpx.Response) -> None:
    directory = Path(__file__).resolve().parents[2] / ".omo/evidence/essay-agent"
    directory.mkdir(parents=True, exist_ok=True)
    lines = [f"scenario: {name}", f"model calls: {len(session.responses.calls)}"]
    lines.extend(f"call: {stage}" for stage in session.responses.calls)
    for response in responses:
        lines.extend((f"HTTP {response.status_code} {response.request.url.path}", response.text))
    for payload in session.responses.payloads:
        lines.extend((f"payload: {type(payload).__name__}", payload.model_dump_json()))
    lines.extend(result.model_dump_json() for result in session.store.attempted)
    _ = (directory / f"task-7-adversarial-{name}.txt").write_text("\n".join(lines))


async def complete(current: Session, form: c.EssayRequest, name: str) -> ChatResponse:
    response = await current.client.post("/chat", json=form.model_dump(mode="json"))
    record(name, current, response)
    assert response.status_code == 200
    result = ChatResponse.model_validate_json(response.text)
    assert result.metadata.persistence_status == "stored"
    assert result.result.body.strip()
    return result


async def lookup_input(current: Session, request_id: UUID, name: str) -> c.EssayRequest:
    response = await current.client.get(f"/runs/{request_id}")
    record(name, current, response)
    assert response.status_code == 200
    lookup = RunLookup.model_validate_json(response.text)
    assert lookup.input is not None
    assert set(lookup.input.model_dump()) == FORM_FIELDS
    raw = TypeAdapter(dict[str, JsonValue]).validate_json(response.text)
    raw_input = raw["input"]
    assert isinstance(raw_input, dict)
    assert set(raw_input) == FORM_FIELDS
    return lookup.input


def record_model(name: str, value: c.ContractModel) -> None:
    directory = Path(__file__).resolve().parents[2] / ".omo/evidence/essay-agent"
    _ = (directory / f"task-7-adversarial-{name}.json").write_text(value.model_dump_json(indent=2))
