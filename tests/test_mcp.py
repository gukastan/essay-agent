"""Real stdio and catalog boundary acceptance for the essay capabilities."""

import json
import os
import time
from pathlib import Path
from typing import Final

import anyio
import pytest
from pydantic import ValidationError

from agent.contract_base import ContractViolationError
from agent.contracts import EvidenceVersion
from agent.mcp_client import SERVER_DIR, MCPClient
from agent.mcp_lifecycle import MCPTimeouts
from agent.mcp_materials import local_guide, local_prompt, search_catalog
from tests.fixtures.mcp_cases import catalog, entry, server_script

EVIDENCE: Final = SERVER_DIR.parent / ".omo/evidence/essay-agent/task-3-mcp-transcript.json"


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.mark.anyio
async def test_real_stdio_capabilities() -> None:
    # Given the actual product server with an empty registered catalog.
    client = MCPClient()
    # When its three capabilities are discovered and used via a subprocess.
    await client.start()
    try:
        tools = await client.list_tools()
        resources = await client.list_resource_templates()
        prompts = await client.list_prompts()
        materials = await client.search_company_job_materials("unregistered fictional company")
        guide = await client.writing_guide("experience")
        prompt = await client.writing_prompt("experience")
        # Then there is no invented company material and the actual policy files are served.
        assert set(client.sessions) == {"essay"}
        assert [tool.name for tool in tools] == ["search_company_job_materials"]
        assert [resource.name for resource in resources] == ["get_writing_guide"]
        assert [item.name for item in prompts] == ["essay_writing_prompt"]
        assert materials == ()
        assert guide == local_guide("experience")
        assert prompt == local_prompt("experience")
        assert not client.warnings
        _ = EVIDENCE.write_text(
            json.dumps(
                {
                    "transport": "actual stdio subprocess",
                    "tools": [tool.name for tool in tools],
                    "resources": [resource.uri_template for resource in resources],
                    "prompts": [item.name for item in prompts],
                    "unregistered_materials": [],
                    "guide": guide,
                    "prompt": prompt,
                    "warnings": client.warnings,
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
    finally:
        await client.stop()
    assert client.sessions == {}


def test_catalog_matches_company_and_role(tmp_path: Path) -> None:
    # Given five explicitly fictional local entries, including another role.
    catalog(
        tmp_path,
        (
            entry("z"),
            entry("c", "engineer"),
            entry("b", "engineer"),
            entry("a"),
            entry("d", "sales"),
        ),
    )
    # When NFC, whitespace and case-insensitive exact matching is used.
    result = search_catalog(tmp_path, "  가상\tCAFÉ  ", " ENGINEER ")
    # Then exact role wins, unrelated role is absent and only three texts survive.
    assert [item.source_id for item in result.materials] == ["b", "c", "a"]
    assert all(
        item.text == (tmp_path / item.relative_path).read_text() for item in result.materials
    )
    assert result.materials[0].source_url == "https://fictional.invalid/reference"


def test_ambiguous_company_no_match(tmp_path: Path) -> None:
    # Given distinct spelling identities that casefold conflates.
    catalog(
        tmp_path,
        (
            entry("a").model_copy(update={"company": "Straße"}),
            entry("b").model_copy(update={"company": "Strasse"}),
        ),
    )
    # When the colliding company key is searched.
    result = search_catalog(tmp_path, "STRASSE", None)
    # Then no identity is guessed.
    assert result.materials == ()


@pytest.mark.parametrize("relative", ["../outside.txt", "/etc/passwd", "https://bad.invalid/x.txt"])
def test_reference_path_outside_catalog_rejected(tmp_path: Path, relative: str) -> None:
    # Given an explicitly registered malicious path.
    catalog(tmp_path, (entry("a").model_copy(update={"relative_path": relative}),))
    # When the actual catalog reader resolves it, then no outside file is read.
    with pytest.raises(ContractViolationError):
        _ = search_catalog(tmp_path, "가상 CAFÉ", None)


def test_reference_symlink_escape_rejected(tmp_path: Path) -> None:
    # Given a registered file symlink escaping the catalog root.
    root = tmp_path / "references"
    root.mkdir()
    outside = tmp_path / "outside.txt"
    _ = outside.write_text("must not be returned")
    (root / "a.txt").symlink_to(outside)
    catalog(root, (entry("a"),))
    # When the actual reader resolves it, then the escape is rejected.
    with pytest.raises(ContractViolationError):
        _ = search_catalog(root, "가상 CAFÉ", None)


@pytest.mark.anyio
async def test_missing_server_script_cleans_up(tmp_path: Path) -> None:
    # Given one valid script followed by a missing script (partial startup).
    pidfile = tmp_path / "pid"
    script = server_script(
        tmp_path,
        f"""import os
from pathlib import Path
from mcp_server import mcp
Path({str(pidfile)!r}).write_text(str(os.getpid()))
mcp.run(transport="stdio", show_banner=False)
""",
    )
    client = MCPClient({"essay": script, "missing": tmp_path / "missing.py"})
    # When startup fails and shutdown runs in the owning task.
    with anyio.fail_after(12):
        await client.start()
        await client.stop()
    # Then no session survives and writing policies remain available.
    assert client.sessions == {}
    assert client.warnings
    assert await client.writing_guide("general") == local_guide("general")
    with pytest.raises(ProcessLookupError):
        os.kill(int(pidfile.read_text()), 0)


@pytest.mark.anyio
async def test_startup_timeout_terminates_process(tmp_path: Path) -> None:
    # Given a process that never speaks MCP and records its PID before blocking.
    pidfile = tmp_path / "pid"
    script = server_script(
        tmp_path,
        f"import os, time\nopen({str(pidfile)!r}, 'w').write(str(os.getpid()))\ntime.sleep(60)\n",
    )
    client = MCPClient({"essay": script}, MCPTimeouts(startup=0.4, call=0.2))
    started = time.monotonic()
    # When startup reaches its finite deadline and joins shutdown.
    with anyio.fail_after(10):
        await client.start()
        startup_elapsed = time.monotonic() - started
        await client.stop()
    # Then process cleanup is real, not just cleared bookkeeping.
    assert startup_elapsed < 0.8
    assert time.monotonic() - started < 10
    assert client.sessions == {}
    with pytest.raises(ProcessLookupError):
        os.kill(int(pidfile.read_text()), 0)
    _ = EVIDENCE.with_name("task-3-cleanup.json").write_text(
        json.dumps(
            {
                "scenario": "unresponsive_stdio_startup",
                "pid": int(pidfile.read_text()),
                "pid_alive_after_stop": False,
                "startup_seconds": startup_elapsed,
                "startup_bound_seconds": 0.4,
                "total_seconds": time.monotonic() - started,
                "sessions_after_stop": len(client.sessions),
                "warnings": client.warnings,
            },
            indent=2,
        ),
        encoding="utf-8",
    )


@pytest.mark.anyio
async def test_mcp_text_is_frozen_in_current_evidence_snapshot(tmp_path: Path) -> None:
    # Given a fictional catalog served by a real stdio subprocess.
    catalog(
        tmp_path,
        (entry("user:collision", "engineer").model_copy(update={"relative_path": "a.txt"}),),
    )
    script = server_script(
        tmp_path,
        f"""from pathlib import Path
from mcp_server import create_server
create_server(Path({str(tmp_path)!r})).run(transport='stdio', show_banner=False)
""",
    )
    client = MCPClient({"essay": script})
    await client.start()
    try:
        # When a successful tool response is frozen and its original file later changes.
        materials = await client.search_company_job_materials("가상 CAFÉ", "engineer")
        snapshot = materials[0].snapshot(EvidenceVersion("ev-current"), 2)
        _ = (tmp_path / "a.txt").write_text("changed later", encoding="utf-8")
        # Then old raw text, Unicode codepoint spans and complete metadata remain unchanged.
        assert snapshot.text == materials[0].text
        assert snapshot.source_id == "mcp:essay:user:collision"
        assert snapshot.metadata.catalog is not None
        assert snapshot.metadata.catalog.relative_path == "a.txt"
        assert snapshot.metadata.catalog.source_id == "user:collision"
        assert snapshot.evidence_version == "ev-current"
        _ = EVIDENCE.with_name("task-3-snapshot.json").write_text(
            snapshot.model_dump_json(indent=2),
            encoding="utf-8",
        )
        assert snapshot.text[snapshot.text.index("👩") :][:3] == "👩‍💻"
        with pytest.raises(ValidationError):
            snapshot.text = "replacement"
    finally:
        await client.stop()


@pytest.mark.anyio
@pytest.mark.parametrize("fault", ["error", "empty", "nontext", "malformed", "timeout", "schema"])
async def test_tool_error_returns_empty_context(tmp_path: Path, fault: str) -> None:
    # Given a real peer injecting a fault at its public capability boundary.
    script = server_script(
        tmp_path,
        f"""from tests.fixtures.mcp_faults import create_fault_server
create_fault_server({fault!r}).run(transport='stdio', show_banner=False)
""",
    )
    client = MCPClient({"essay": script}, MCPTimeouts(call=0.3))
    # When the tool fails, local guide/prompt fallback and shutdown remain finite.
    with anyio.fail_after(12):
        await client.start()
        try:
            assert client.sessions
            materials = await client.search_company_job_materials("fictional")
            guide = await client.writing_guide("experience")
            prompt = await client.writing_prompt("experience")
        finally:
            await client.stop()
    # Then no unsupported material survives, and policy comes from the shared files.
    assert materials == ()
    assert guide == local_guide("experience")
    assert prompt == local_prompt("experience")
    assert client.warnings
    assert client.sessions == {}


@pytest.mark.parametrize("question_type", ["../procedure", "procedure", "unknown", ""])
def test_guide_allowlist_rejects_arbitrary_paths(question_type: str) -> None:
    # Given an unregistered question type, when a guide is requested, then reject it.
    with pytest.raises(ValidationError):
        _ = local_guide(question_type)
