"""Test-only loopback fault server; never imported by production entrypoints."""

import os
import sys
from pathlib import Path
from typing import Literal

import anyio
import uvicorn
from pydantic import TypeAdapter
from typing_extensions import override

from agent.app_runtime import AppSettings, RuntimeFactories
from agent.contracts import ContractModel
from agent.essay_llm import GenerationResult, Output, OutputRecovery, Stage
from agent.fake_llm import FakeLLM
from server import create_app
from tests.api_adversarial_support import Fault, FaultStore, RecordingResponses
from tests.review_graph_support import Cycles
from web_demo_server import ProxySettings
from web_demo_server import create_app as create_proxy

Mode = Literal[
    "normal",
    "slow",
    "analysis",
    "title",
    "repair",
    "repair1",
    "repair2",
    "failed",
    "unknown",
    "workflow",
    "execution",
    "questions",
    "resolved",
]


class Responses:
    def __init__(self, mode: Mode, directory: Path) -> None:
        self.directory: Path = directory
        directory.mkdir(parents=True, exist_ok=True)
        self.count: int = 0
        failures: dict[str, Stage] = {
            "analysis": "analyze_context",
            "title": "title_and_review",
            "repair": "repair_draft",
        }
        failure = failures.get(mode)
        self.cycles: Cycles = Cycles(
            repairs=2 if mode in ("repair2", "repair") else int(mode == "repair1"), failure=failure
        )
        self.questions: RecordingResponses = RecordingResponses(
            mode="resolved" if mode == "resolved" else "questions"
        )
        self.mode: Mode = mode

    def __call__(self, stage: Stage, payload: ContractModel, output_model: type[Output]) -> Output:
        self.count += 1
        _ = (self.directory / f"{self.count:02d}-{stage}-payload.json").write_text(
            payload.model_dump_json(indent=2)
        )
        if self.mode == "execution" and stage == "write_sections":
            message = "Synthetic workflow failure after persisted parent loading"
            raise RuntimeError(message)
        output = (
            self.questions(stage, payload, output_model)
            if self.mode in ("questions", "resolved")
            else self.cycles(stage, payload, output_model)
        )
        _ = (self.directory / f"{self.count:02d}-{stage}-output.json").write_text(
            output.model_dump_json(indent=2)
        )
        return output


class SlowLLM(FakeLLM):
    @override
    async def generate(
        self,
        stage: Stage,
        payload: ContractModel,
        output_model: type[Output],
        *,
        recover: OutputRecovery | None = None,
    ) -> GenerationResult[Output]:
        await anyio.sleep(2)
        return await super().generate(stage, payload, output_model, recover=recover)


def main() -> None:
    kind, port, location, mode_value, artifact = sys.argv[1:] or [
        os.environ[key]
        for key in (
            "ESSAY_TEST_KIND",
            "ESSAY_TEST_PORT",
            "ESSAY_TEST_LOCATION",
            "ESSAY_TEST_MODE",
            "ESSAY_TEST_ARTIFACT",
        )
    ]
    if kind == "proxy":
        application = create_proxy(ProxySettings(backend=location))
    else:
        mode = TypeAdapter(Mode).validate_python(mode_value)
        responses = Responses(mode, Path(artifact))
        fault: Fault = TypeAdapter(Fault).validate_python(
            mode if mode in ("failed", "unknown", "workflow") else "none"
        )
        adapter = SlowLLM if mode == "slow" else FakeLLM
        factories = RuntimeFactories(
            fast=lambda _: adapter("fast", responses),
            quality=lambda _: adapter("quality", responses),
            store=lambda path: FaultStore(path, fault),
        )
        application = create_app(
            AppSettings(backend="fake", db_path=Path(location), mcp_enabled=True), factories
        )
    uvicorn.run(application, host="127.0.0.1", port=int(port), log_level="warning")


if __name__ == "__main__":
    main()
