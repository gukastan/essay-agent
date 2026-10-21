import json
import os
import signal
import socket
import subprocess
import time
from collections.abc import Generator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO

import httpx
from pydantic import JsonValue, TypeAdapter

from agent.api_models import HealthResponse
from tests.e2e_server import Mode

EVIDENCE = Path("../.omo/evidence/essay-agent")


def free_port() -> int:
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        return TypeAdapter(tuple[str, int]).validate_python(listener.getsockname())[1]


@dataclass(frozen=True, slots=True)
class Process:
    child: subprocess.Popen[bytes]
    log: BinaryIO
    url: str

    def stop(self) -> None:
        if self.child.poll() is None:
            self.child.terminate()
            try:
                _ = self.child.wait(timeout=15)
            except subprocess.TimeoutExpired:
                self.child.kill()
                _ = self.child.wait(timeout=5)
        self.log.close()
        try:
            os.killpg(self.child.pid, signal.SIGTERM)
        except ProcessLookupError:
            return


def wait_ready(process: Process) -> None:
    with httpx.Client(base_url=process.url, trust_env=False) as client:
        deadline = time.monotonic() + 20
        while time.monotonic() < deadline:
            if process.child.poll() is not None:
                message = "Owned test server exited during startup"
                raise RuntimeError(message)
            try:
                response = client.get("/health")
                if response.status_code == 200:
                    health = HealthResponse.model_validate_json(response.text)
                    assert health.llm_backend == "fake"
                    assert health.mcp_status == "ready"
                    return
            except httpx.RequestError:
                time.sleep(0.05)
        message = "Owned test server startup deadline"
        raise TimeoutError(message)


def start(kind: str, location: str, mode: Mode, directory: Path) -> Process:
    directory.mkdir(parents=True, exist_ok=True)
    port = free_port()
    log = (directory / f"{kind}.log").open("wb")
    child = subprocess.Popen(
        [".venv/bin/python", "-m", "tests.e2e_server"],
        stdout=log,
        stderr=subprocess.STDOUT,
        env={
            "PATH": os.defpath,
            "ESSAY_LOAD_DOTENV": "0",
            "PYTHONUNBUFFERED": "1",
            "ESSAY_TEST_KIND": kind,
            "ESSAY_TEST_PORT": str(port),
            "ESSAY_TEST_LOCATION": location,
            "ESSAY_TEST_MODE": mode,
            "ESSAY_TEST_ARTIFACT": str(directory),
        },
        start_new_session=True,
    )
    process = Process(child, log, f"http://127.0.0.1:{port}")
    try:
        wait_ready(process)
    except (RuntimeError, TimeoutError, ValueError, AssertionError):
        process.stop()
        raise
    else:
        return process


@dataclass(frozen=True, slots=True)
class Stack:
    backend: Process
    proxy: Process
    client: httpx.Client
    directory: Path


@contextmanager
def running(database: Path, mode: Mode, name: str) -> Generator[Stack]:
    directory = EVIDENCE / f"task-10-{name}"
    backend = start("backend", str(database), mode, directory)
    proxy: Process | None = None
    try:
        proxy = start("proxy", backend.url, mode, directory)
        with httpx.Client(base_url=proxy.url, timeout=30, trust_env=False) as client:
            yield Stack(backend, proxy, client, directory)
    finally:
        if proxy is not None:
            proxy.stop()
        backend.stop()
        _ = (directory / "processes.json").write_text(
            json.dumps(
                {
                    "backend_pid": backend.child.pid,
                    "backend_exit": backend.child.returncode,
                    "proxy_pid": proxy.child.pid if proxy else None,
                    "proxy_exit": proxy.child.returncode if proxy else None,
                },
                indent=2,
            )
        )


def record(name: str, response: httpx.Response) -> None:
    EVIDENCE.mkdir(parents=True, exist_ok=True)
    content = (
        json.dumps(
            {
                "status": response.status_code,
                "body": TypeAdapter(JsonValue).validate_json(response.text),
            },
            ensure_ascii=False,
            indent=2,
        )
        if name.endswith(".json")
        else f"HTTP {response.status_code}\n{response.text}"
    )
    _ = (EVIDENCE / name).write_text(content, encoding="utf-8")
