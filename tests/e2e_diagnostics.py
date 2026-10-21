"""Root-operated live diagnostic entrypoint with a strict safe-metadata allowlist."""

import json
import re
import sys
from collections.abc import Callable
from contextvars import ContextVar
from dataclasses import replace
from pathlib import Path
from types import FrameType
from typing import TypeVar
from uuid import uuid4

import uvicorn
from pydantic import TypeAdapter, ValidationError

from agent.app_runtime import RuntimeFactories, load_settings
from agent.contracts import ContractModel, ContractViolation
from agent.essay_llm import (
    EssayLLM,
    GenerationError,
    GenerationResult,
    GenerationUsage,
    Output,
    OutputRecovery,
    Stage,
)
from agent.openai_llm import OpenAIFastLLM, OpenAIQualityLLM
from server import create_app

ACTIVE: ContextVar[tuple[Stage, list[str]] | None] = ContextVar("diagnostic_stage", default=None)
TraceValue = TypeVar("TraceValue")
Trace = Callable[[FrameType, str, TraceValue], "Trace[TraceValue]"]


def trace(frame: FrameType, event: str, arg: TraceValue) -> Trace[TraceValue]:
    del frame
    active = ACTIVE.get()
    if event == "exception" and active is not None:
        values = TypeAdapter(tuple[object, ...]).validate_python(arg)
        error = values[1]
        if isinstance(error, ContractViolation) and re.fullmatch(r"[a-z_]{1,80}", error.code):
            if error.code not in active[1]:
                active[1].append(error.code)
        elif isinstance(error, ValidationError):
            code = f"pydantic_validation_count_{error.error_count()}"
            if code not in active[1]:
                active[1].append(code)
    return trace


class DiagnosticLLM:
    def __init__(self, inner: EssayLLM, destination: Path, *, capture: bool = False) -> None:
        self.inner: EssayLLM = inner
        self.destination: Path = destination
        self.capture: bool = capture

    async def aclose(self) -> None:
        await self.inner.aclose()

    def record(self, stage: Stage, kind: str, codes: list[str], usage: GenerationUsage) -> None:
        with self.destination.open("a", encoding="utf-8") as output:
            _ = output.write(
                json.dumps(
                    {
                        "stage": stage,
                        "kind": kind,
                        "contract_codes": codes,
                        "usage": usage.model_dump(mode="json"),
                    }
                )
                + "\n"
            )

    async def generate(
        self,
        stage: Stage,
        payload: ContractModel,
        output_model: type[Output],
        *,
        recover: OutputRecovery | None = None,
    ) -> GenerationResult[Output]:
        codes: list[str] = []
        token = ACTIVE.set((stage, codes))
        try:
            result = await self.inner.generate(stage, payload, output_model, recover=recover)
        except GenerationError as error:
            self.record(stage, error.kind.value, codes, error.usage)
            raise
        else:
            self.record(stage, "success", codes, result.usage)
            if self.capture:
                directory = self.destination.with_suffix(".validated")
                directory.mkdir(parents=True, exist_ok=True, mode=0o700)
                with (directory / f"{stage}-{uuid4()}.json").open("x", encoding="utf-8") as output:
                    _ = output.write(result.output.model_dump_json(indent=2))
            return result
        finally:
            ACTIVE.reset(token)


def main() -> None:
    port, database, destination = sys.argv[1:4]
    capture = sys.argv[4:] == ["--capture-validated"]
    path = Path(destination)
    path.parent.mkdir(parents=True, exist_ok=True)
    settings = load_settings()
    settings = replace(settings, db_path=Path(database))
    factories = RuntimeFactories(
        fast=lambda config: DiagnosticLLM(OpenAIFastLLM(config.fast_model), path, capture=capture),
        quality=lambda config: DiagnosticLLM(
            OpenAIQualityLLM(config.quality_model), path, capture=capture
        ),
    )
    sys.settrace(trace)
    try:
        uvicorn.run(
            create_app(settings, factories), host="127.0.0.1", port=int(port), log_level="warning"
        )
    finally:
        sys.settrace(None)


if __name__ == "__main__":
    main()
