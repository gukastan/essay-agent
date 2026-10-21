import signal
import socket
import subprocess
import time
from pathlib import Path

import httpx
import pytest
from pydantic import TypeAdapter

from agent.api_models import ChatResponse, HealthResponse
from agent.contracts import ContractModel
from tests.launcher_support import (
    ROOT,
    environment,
    fixture_project,
    free_port,
    launched,
    pid_alive,
    wait_ready,
)


def test_setup_preserves_existing_environment(tmp_path: Path) -> None:
    (tmp_path / "sh").mkdir()
    _ = (tmp_path / "sh/setup_venv.sh").write_bytes((ROOT / "sh/setup_venv.sh").read_bytes())
    (tmp_path / ".venv/bin").mkdir(parents=True)
    python = tmp_path / ".venv/bin/python"
    _ = python.write_text("#!/bin/sh\nexit 0\n")
    python.chmod(0o700)
    marker = tmp_path / ".venv/preserve.txt"
    _ = marker.write_text("existing environment")
    uv = tmp_path / "uv"
    _ = uv.write_text('#!/bin/sh\nprintf "%s\\n" "$*" >> uv.log\n')
    uv.chmod(0o700)
    result = subprocess.run(
        ["/bin/bash", "sh/setup_venv.sh"],
        cwd=tmp_path,
        env={"PATH": str(tmp_path) + ":/usr/bin:/bin"},
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0
    assert (
        tmp_path / "uv.log"
    ).read_text() == "pip install --python .venv/bin/python -r requirements.txt\n"
    assert marker.read_text() == "existing environment"


def test_http_error_never_becomes_ready_and_owned_child_is_reaped(tmp_path: Path) -> None:
    fixture_project(tmp_path)
    env = dict(environment(free_port()))
    env["STUB_HTTP"] = "500"
    with launched(tmp_path, env) as process:
        assert process.wait(timeout=25) == 1
    log = (tmp_path / "run_agent_openai.sh.log").read_text()
    assert "readiness timed out" in log
    assert "Ready at" not in log
    child = ChildRecord.model_validate_json((tmp_path / "child.json").read_text()).pid
    assert not pid_alive(child)


@pytest.mark.parametrize("value", ["0", "65536", "not-a-port"])
def test_invalid_port_rejected_before_start(tmp_path: Path, value: str) -> None:
    fixture_project(tmp_path)
    env = dict(environment(free_port()))
    env["AGENT_PORT"] = value
    with launched(tmp_path, env) as process:
        assert process.wait(timeout=5) != 0
    assert not (tmp_path / "child.json").exists()


def test_frontend_backend_down_has_actionable_error(tmp_path: Path) -> None:
    fixture_project(tmp_path)
    with launched(tmp_path, environment(free_port()), "run_frontend.sh") as process:
        assert process.wait(timeout=5) != 0
    assert "bash sh/run_agent_openai.sh" in (tmp_path / "run_frontend.sh.log").read_text()
    assert not (tmp_path / "child.json").exists()


def test_socket_stays_reserved_until_child_accepts_health(tmp_path: Path) -> None:
    fixture_project(tmp_path)
    port = free_port()
    env = dict(environment(port))
    env["STUB_DELAY"] = "1"
    with launched(tmp_path, env) as process:
        deadline = time.monotonic() + 5
        while not (tmp_path / "child.json").exists() and time.monotonic() < deadline:
            time.sleep(0.01)
        assert (tmp_path / "child.json").exists()
        with socket.socket() as competing, pytest.raises(OSError, match="Address already in use"):
            competing.bind(("127.0.0.1", port))
        wait_ready(process, port, tmp_path / "run_agent_openai.sh.log")


def test_owned_port_can_restart_after_clean_shutdown(tmp_path: Path) -> None:
    fixture_project(tmp_path)
    port = free_port()
    for _ in range(2):
        with launched(tmp_path, environment(port)) as process:
            wait_ready(process, port, tmp_path / "run_agent_openai.sh.log")


@pytest.mark.parametrize(
    "url", ["http://example.com", "http://127.0.0.1:bad", "http://127.0.0.1:0"]
)
def test_proxy_origin_is_loopback_with_valid_port(tmp_path: Path, url: str) -> None:
    fixture_project(tmp_path)
    env = dict(environment(free_port()))
    env["AGENT_BASE_URL"] = url
    with launched(tmp_path, env, "run_frontend.sh") as process:
        assert process.wait(timeout=5) != 0
    assert "ERROR: AGENT_BASE_URL" in (tmp_path / "run_frontend.sh.log").read_text()
    assert not (tmp_path / "child.json").exists()


class ChildRecord(ContractModel):
    pid: int
    env: dict[str, str | None]


def test_start_stop_preserves_db_and_only_owned_pid_stopped(tmp_path: Path) -> None:
    fixture_project(tmp_path)
    sentinels = dict.fromkeys(("session.db", "session.db-wal", "session.db-shm"), b"preserve-me")
    for name, content in sentinels.items():
        _ = (tmp_path / name).write_bytes(content)
    port = free_port()
    with launched(tmp_path, environment(port)) as process:
        wait_ready(process, port, tmp_path / "run_agent_openai.sh.log")
        child = ChildRecord.model_validate_json((tmp_path / "child.json").read_text()).pid
        process.send_signal(signal.SIGINT)
        assert process.wait(timeout=15) == 0
    assert (tmp_path / "signals.txt").read_text() == str(child)
    assert not pid_alive(child)
    for name, content in sentinels.items():
        assert (tmp_path / name).read_bytes() == content


def test_env_model_values_preserved(tmp_path: Path) -> None:
    fixture_project(tmp_path)
    _ = (tmp_path / ".env").write_text(
        "OPENAI_FAST_MODEL=dotenv-fast\nLANGCHAIN_PROJECT=dotenv-project\n"
    )
    env = dict(environment(free_port()))
    env.update(
        ESSAY_LOAD_DOTENV="1",
        OPENAI_FAST_MODEL="explicit-fast",
        OPENAI_QUALITY_MODEL="explicit-quality",
        LANGCHAIN_PROJECT="explicit-project",
        ESSAY_DB_PATH="custom.db",
    )
    with launched(tmp_path, env) as process:
        wait_ready(process, int(env["AGENT_PORT"]), tmp_path / "run_agent_openai.sh.log")
        recorded = ChildRecord.model_validate_json((tmp_path / "child.json").read_text()).env
        assert all(recorded[name] == env[name] for name in recorded)


def test_busy_port_does_not_kill_owner(tmp_path: Path) -> None:
    fixture_project(tmp_path)
    with socket.socket() as owner:
        owner.bind(("127.0.0.1", 0))
        owner.listen()
        port = TypeAdapter(tuple[str, int]).validate_python(owner.getsockname())[1]
        with launched(tmp_path, environment(port)) as process:
            assert process.wait(timeout=5) != 0
        assert owner.fileno() >= 0
        assert not (tmp_path / "child.json").exists()
        assert not (tmp_path / "signals.txt").exists()


@pytest.mark.parametrize("key", ["", " ", "sk-..."])
def test_missing_openai_key_clear_error(tmp_path: Path, key: str) -> None:
    fixture_project(tmp_path)
    env = dict(environment(free_port()))
    env.update(LLM_BACKEND="openai", OPENAI_API_KEY=key)
    with launched(tmp_path, env) as process:
        assert process.wait(timeout=5) != 0
    assert "OPENAI_API_KEY" in (tmp_path / "run_agent_openai.sh.log").read_text()
    assert not (tmp_path / "child.json").exists()


def test_ollama_backend_removed(tmp_path: Path) -> None:
    fixture_project(tmp_path)
    env = dict(environment(free_port()))
    env["LLM_BACKEND"] = "ollama"
    with launched(tmp_path, env) as process:
        assert process.wait(timeout=5) != 0
    assert "must be openai or fake" in (tmp_path / "run_agent_openai.sh.log").read_text()
    assert not (tmp_path / "child.json").exists()


def test_child_failure_is_not_readiness(tmp_path: Path) -> None:
    fixture_project(tmp_path)
    env = dict(environment(free_port()))
    env["STUB_EXIT"] = "1"
    with launched(tmp_path, env) as process:
        assert process.wait(timeout=5) == 7
    assert "Ready at" not in (tmp_path / "run_agent_openai.sh.log").read_text()
    assert not (tmp_path / "signals.txt").exists()


def test_no_tracing_key_required_for_fake_and_proxy_isolation(tmp_path: Path) -> None:
    port, frontend = free_port(), free_port()
    env = dict(environment(port))
    env.update(ESSAY_DB_PATH=str(tmp_path / "actual.db"), FRONTEND_PORT=str(frontend))
    with launched(ROOT, env) as backend:
        wait_ready(backend, port, ROOT / "run_agent_openai.sh.log")
        with launched(ROOT, env, "run_frontend.sh") as proxy:
            wait_ready(proxy, frontend, ROOT / "run_frontend.sh.log")
            with httpx.Client(timeout=10, trust_env=False) as client:
                health = client.get(f"http://127.0.0.1:{frontend}/health")
                assert HealthResponse.model_validate_json(health.text).llm_backend == "fake"
                assert client.get(f"http://127.0.0.1:{frontend}/").status_code == 200
                response = client.post(f"http://127.0.0.1:{frontend}/chat", json={})
                assert response.status_code == 200
                parsed = ChatResponse.model_validate_json(response.text)
                assert parsed.result.body
                assert parsed.metadata.persistence_status == "stored"
                artifact = ROOT.parent / ".omo/evidence/essay-agent/task-9-smoke.json"
                artifact.parent.mkdir(parents=True, exist_ok=True)
                _ = artifact.write_text(response.text)
        assert backend.poll() is None
        with httpx.Client(timeout=1, trust_env=False) as client:
            assert client.get(f"http://127.0.0.1:{port}/health").status_code == 200
    assert (tmp_path / "actual.db").exists()
