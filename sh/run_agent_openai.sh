#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
if [ ! -x .venv/bin/python ]; then
    echo 'ERROR: run bash sh/setup_venv.sh first.' >&2
    exit 1
fi
exec .venv/bin/python - "$@" <<'PY'
"""Supervise one loopback child without touching another process or database."""

import os
import signal
import socket
import subprocess
import sys
import time
from pathlib import Path
from threading import Event
from types import FrameType
from typing import Final, NoReturn
from urllib.parse import urlsplit

import httpx
from dotenv import load_dotenv

MAX_PORT: Final = 65535


def _fail(message: str) -> NoReturn:
    raise SystemExit(message)


def _message(message: str) -> None:
    _ = sys.stdout.write(message + "\n")
    _ = sys.stdout.flush()


def _port_value(name: str, default: str) -> int:
    value = os.getenv(name, default)
    if not value.isdecimal() or not 1 <= int(value) <= MAX_PORT:
        _fail(f"ERROR: {name} must be a port from 1 to 65535.")
    return int(value)


def _healthy(client: httpx.Client, url: str) -> bool:
    try:
        return client.get(url).is_success
    except httpx.RequestError:
        return False


def _configuration() -> tuple[bool, int, str]:
    if os.getenv("ESSAY_LOAD_DOTENV", "1") == "1":
        _ = load_dotenv(Path.cwd() / ".env", override=False)
    _ = os.environ.setdefault("LANGCHAIN_TRACING_V2", "false")
    frontend = sys.argv[1:] == ["--frontend"]
    if sys.argv[1:] and not frontend:
        _fail("ERROR: unexpected launcher argument.")
    agent_port = _port_value("AGENT_PORT", "8100")
    frontend_port = _port_value("FRONTEND_PORT", "8600")
    port = frontend_port if frontend else agent_port
    backend = os.getenv("LLM_BACKEND", "openai")
    if not frontend:
        if backend not in ("openai", "fake"):
            _fail("ERROR: LLM_BACKEND must be openai or fake.")
        key = os.getenv("OPENAI_API_KEY", "").strip()
        if backend == "openai" and (not key or key in ("sk-...", "your-key", "YOUR_API_KEY")):
            _fail("ERROR: set OPENAI_API_KEY, or use LLM_BACKEND=fake.")
    base = os.getenv("AGENT_BASE_URL", f"http://127.0.0.1:{agent_port}")
    try:
        parsed = urlsplit(base)
        base_port = parsed.port
    except ValueError:
        _fail("ERROR: AGENT_BASE_URL must have a valid HTTP port.")
    if (
        parsed.scheme != "http"
        or parsed.hostname not in ("127.0.0.1", "localhost")
        or parsed.username
        or parsed.password
        or parsed.path not in ("", "/")
        or parsed.query
        or parsed.fragment
        or base_port == 0
    ):
        _fail("ERROR: AGENT_BASE_URL must be a loopback HTTP origin.")
    os.environ["AGENT_BASE_URL"] = base
    os.environ["AGENT_PORT"] = str(agent_port)
    os.environ["FRONTEND_PORT"] = str(frontend_port)
    os.environ["ESSAY_LAUNCH_ROLE"] = "frontend" if frontend else "backend"
    return frontend, port, base


def _spawn(port: int) -> subprocess.Popen[bytes]:
    with socket.socket() as listener:
        try:
            listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            listener.bind(("127.0.0.1", port))
            listener.listen()
        except OSError:
            _fail(f"ERROR: port {port} is in use; its owner was not stopped.")
        os.environ["ESSAY_LISTEN_FD"] = str(listener.fileno())
        return subprocess.Popen(
            [
                "./.venv/bin/python",
                "-c",
                """
import os,socket,uvicorn
if os.environ['ESSAY_LAUNCH_ROLE']=='frontend':
    from web_demo_server import create_app,ProxySettings
    app=create_app(ProxySettings(backend=os.environ['AGENT_BASE_URL']))
else:
    from server import app
listener=socket.socket(fileno=int(os.environ['ESSAY_LISTEN_FD']))
uvicorn.Server(uvicorn.Config(app,host='127.0.0.1',log_level='warning')).run(sockets=[listener])
""",
            ],
            pass_fds=(listener.fileno(),),
        )


def _watch(child: subprocess.Popen[bytes], client: httpx.Client, port: int, stopped: Event) -> int:
    deadline = time.monotonic() + 20
    while not stopped.is_set() and time.monotonic() < deadline:
        status = child.poll()
        if status is not None:
            _message("ERROR: child exited before readiness.")
            return status or 1
        if _healthy(client, f"http://127.0.0.1:{port}/health") and child.poll() is None:
            _message(f"Ready at http://127.0.0.1:{port}")
            break
        _ = stopped.wait(0.1)
    else:
        _message("ERROR: startup interrupted or readiness timed out.")
        return 1
    while not stopped.wait(0.1):
        status = child.poll()
        if status is not None:
            return status
    return 0


def _main() -> int:
    frontend, port, base = _configuration()
    stopped = Event()

    def stop(signum: int, frame: FrameType | None) -> None:
        del signum, frame
        stopped.set()

    _ = signal.signal(signal.SIGINT, stop)
    _ = signal.signal(signal.SIGTERM, stop)
    with httpx.Client(timeout=0.5, trust_env=False) as client:
        if frontend and not _healthy(client, base.rstrip("/") + "/health"):
            _fail("ERROR: backend unavailable; run bash sh/run_agent_openai.sh first.")
        child = _spawn(port)
        _message(f"Started owned child PID={child.pid}")
        try:
            return _watch(child, client, port, stopped)
        finally:
            if child.poll() is None:
                child.terminate()
                try:
                    _ = child.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    _fail(f"ERROR: owned child PID={child.pid} did not stop within 10s.")
            _message(f"Owned child PID={child.pid} reaped.")


raise SystemExit(_main())
PY
