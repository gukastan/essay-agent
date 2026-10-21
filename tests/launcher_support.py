from __future__ import annotations

import os
import signal
import socket
import subprocess
import time
from contextlib import contextmanager
from pathlib import Path
from typing import TYPE_CHECKING, Final

import httpx
from pydantic import TypeAdapter

if TYPE_CHECKING:
    from collections.abc import Generator, Mapping

ROOT: Final = Path(__file__).resolve().parents[1]
PYTHON: Final = ROOT / ".venv/bin/python"
STUB: Final = """import json,os,signal,sys,time
from http.server import BaseHTTPRequestHandler,HTTPServer
from pathlib import Path
def run(sockets):
    keys=('OPENAI_FAST_MODEL','OPENAI_QUALITY_MODEL','ESSAY_DB_PATH','LANGCHAIN_PROJECT','AGENT_PORT')
    data={'pid':os.getpid(),'env':{k:os.getenv(k) for k in keys}}
    Path('child.json').write_text(json.dumps(data))
    def stop(signum,frame):
        Path('signals.txt').write_text(str(os.getpid()))
        sys.exit(0)
    signal.signal(signal.SIGTERM,stop)
    if os.getenv('STUB_DELAY'): time.sleep(1)
    if os.getenv('STUB_EXIT'): sys.exit(7)
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(int(os.getenv('STUB_HTTP','200')))
            self.end_headers()
            self.wfile.write(b'{}')
        def log_message(self,*args): return
    listener=sockets[0]
    server=HTTPServer(listener.getsockname(),Handler,bind_and_activate=False)
    server.socket.close()
    server.socket=listener
    server.server_activate()
    server.serve_forever()
class Config:
    def __init__(self,*args,**kwargs): return
class Server:
    def __init__(self,config): return
    def run(self,sockets): run(sockets)
"""


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return TypeAdapter(tuple[str, int]).validate_python(sock.getsockname())[1]


def environment(port: int) -> Mapping[str, str]:
    return {
        "PATH": "/usr/bin:/bin",
        "ESSAY_LOAD_DOTENV": "0",
        "LLM_BACKEND": "fake",
        "LANGCHAIN_TRACING_V2": "false",
        "AGENT_PORT": str(port),
        "ESSAY_MCP_ENABLED": "0",
    }


def fixture_project(directory: Path) -> None:
    (directory / "sh").mkdir()
    (directory / ".venv/bin").mkdir(parents=True)
    for name in ("run_agent_openai.sh", "run_frontend.sh"):
        _ = (directory / "sh" / name).write_bytes((ROOT / "sh" / name).read_bytes())
    executable = directory / ".venv/bin/python"
    _ = executable.write_text(f'#!/bin/sh\nexec "{PYTHON}" "$@"\n')
    executable.chmod(0o700)
    _ = (directory / "uvicorn.py").write_text(STUB)
    _ = (directory / "server.py").write_text("app=None\n")


@contextmanager
def launched(
    directory: Path, env: Mapping[str, str], name: str = "run_agent_openai.sh"
) -> Generator[subprocess.Popen[str]]:
    with (directory / (name + ".log")).open("w") as log:
        if name == "run_frontend.sh":
            process = subprocess.Popen(
                ["/bin/bash", "sh/run_frontend.sh"],
                cwd=directory,
                env=env,
                stdout=log,
                stderr=subprocess.STDOUT,
                text=True,
            )
        else:
            process = subprocess.Popen(
                ["/bin/bash", "sh/run_agent_openai.sh"],
                cwd=directory,
                env=env,
                stdout=log,
                stderr=subprocess.STDOUT,
                text=True,
            )
        try:
            yield process
        finally:
            if process.poll() is None:
                process.send_signal(signal.SIGTERM)
            _ = process.wait(timeout=15)


def wait_ready(process: subprocess.Popen[str], port: int, log: Path) -> None:
    deadline = time.monotonic() + 10
    with httpx.Client(timeout=0.2, trust_env=False) as client:
        while time.monotonic() < deadline:
            assert process.poll() is None, "launcher exited before health"
            try:
                if (
                    client.get(f"http://127.0.0.1:{port}/health").is_success
                    and "Ready at" in log.read_text()
                ):
                    return
            except httpx.RequestError:
                time.sleep(0.05)
    pytest_message = "launcher did not become healthy"
    raise AssertionError(pytest_message)


def pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    return True
