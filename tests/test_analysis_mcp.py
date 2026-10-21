import json
import os
from pathlib import Path

import anyio
import pytest

from agent.mcp_client import MCPClient
from tests.analysis_support import Responses, execute, request_for, seed
from tests.fixtures.mcp_cases import catalog, entry, server_script


def test_real_mcp_snapshot_survives_source_change_and_subprocess_closes(tmp_path: Path) -> None:
    catalog(tmp_path, (entry("doc"),))
    pid_path = tmp_path / "pid"
    script = server_script(
        tmp_path,
        "\n".join(
            (
                "import os",
                "from pathlib import Path",
                "from mcp_server import create_server",
                f"Path({str(pid_path)!r}).write_text(str(os.getpid()))",
                f"create_server(Path({str(tmp_path)!r})).run(transport='stdio', show_banner=False)",
            )
        ),
    )
    original = (tmp_path / "doc.txt").read_text()
    client = MCPClient({"essay": script})

    evidence = Path(__file__).resolve().parents[2] / ".omo/evidence/essay-agent/task-4"

    async def scenario() -> None:
        await client.start()
        try:
            client.warnings.append("old_service_diagnostic")
            state = seed(request_for().model_copy(update={"company_name": "가상 CAFÉ"}))
            result = await execute(state, Responses(), client)
            source = next(s for s in result.sources if s.metadata.origin == "mcp")
            assert source.text == original
            assert source.metadata.catalog is not None
            assert source.source_id == "mcp:essay:doc"
            assert result.analysis.research_status == "available"
            assert result.technical_issues == ()
            _ = await anyio.Path(tmp_path / "doc.txt").write_text("changed after snapshot")
            assert source.text == original
            artifact = evidence / "mcp-surface.json"
            _ = await anyio.Path(artifact).write_text(
                result.model_dump_json(indent=2), encoding="utf-8"
            )
        finally:
            await client.stop()

    anyio.run(scenario)
    assert client.sessions == {}
    pid = int(pid_path.read_text())
    with pytest.raises(ProcessLookupError):
        os.kill(pid, 0)
    artifact = Path(__file__).resolve().parents[2] / ".omo/evidence/essay-agent/task-4/cleanup.json"
    _ = artifact.write_text(json.dumps({"pid": pid, "process_gone": True, "sessions": 0}))
