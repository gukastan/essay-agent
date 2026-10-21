"""Local fictional catalogs and subprocess launchers for MCP acceptance."""

import json
from pathlib import Path

from agent.mcp_client import SERVER_DIR
from agent.mcp_materials import CatalogEntry


def catalog(tmp_path: Path, entries: tuple[CatalogEntry, ...]) -> None:
    _ = (tmp_path / "catalog.json").write_text(
        json.dumps([entry.model_dump() for entry in entries]),
        encoding="utf-8",
    )
    for entry in entries:
        path = tmp_path / entry.relative_path
        if not path.exists() and path.parent == tmp_path:
            _ = path.write_text(
                f"가상기업 자료 {entry.source_id}: 행동 가이드 👩‍💻\n", encoding="utf-8"
            )


def entry(source_id: str, role: str | None = None) -> CatalogEntry:
    return CatalogEntry(
        source_id=source_id,
        company="가상  CAFÉ",
        job_title=role,
        title=f"Fictional material {source_id}",
        relative_path=f"{source_id}.txt",
        source_url="https://fictional.invalid/reference",
        registered_at="2026-10-22",
        published_at=None,
    )


def server_script(tmp_path: Path, body: str) -> Path:
    path = tmp_path / "server.py"
    _ = path.write_text(
        f"import sys\nsys.path.insert(0, {str(SERVER_DIR)!r})\n" + body,
        encoding="utf-8",
    )
    return path
