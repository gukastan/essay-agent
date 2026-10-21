"""SQLite serialization with validated rows and retained legacy messages."""

import sqlite3
from collections.abc import Generator
from contextlib import contextmanager
from pathlib import Path
from threading import RLock
from typing import TypeAlias

from pydantic import RootModel, ValidationError

from .store_models import RunRecord, StoreUnavailableError

SqlValue: TypeAlias = str | int | None

SELECT_RUN = """SELECT json_object(
 'request_hash', request_hash, 'status', status, 'input', json(input_json),
 'evidence_version', evidence_version,
 'revision_context', json(revision_context_json), 'result', json(result_json),
 'error', json(error_json), 'created_at', created_at, 'updated_at', updated_at)
 FROM essay_runs"""


class _TextRows(RootModel[tuple[tuple[str], ...]]):
    pass


class _Messages(RootModel[list[tuple[str, str]]]):
    pass


class StoreDatabase:
    """One serialized connection; callers offload operations from async handlers."""

    def __init__(self, path: Path) -> None:
        """Create only additive tables; bound SQLite lock waits to two seconds."""
        self.lock: RLock = RLock()
        try:
            self.connection: sqlite3.Connection = sqlite3.connect(
                path, timeout=2, check_same_thread=False, isolation_level=None
            )
            _ = self.connection.executescript("""
                CREATE TABLE IF NOT EXISTS messages (
                    thread_id TEXT, role TEXT, content TEXT, created TEXT);
                CREATE TABLE IF NOT EXISTS essay_runs (
                    request_id TEXT PRIMARY KEY,
                    request_hash TEXT NOT NULL,
                    thread_id TEXT NOT NULL,
                    document_id TEXT NOT NULL,
                    parent_version_id TEXT,
                    version_id TEXT UNIQUE,
                    evidence_version TEXT NOT NULL,
                    status TEXT NOT NULL
                        CHECK(status IN ('running','completed','failed','interrupted')),
                    input_json TEXT NOT NULL,
                    revision_context_json TEXT NOT NULL,
                    result_json TEXT,
                    error_json TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL);
                CREATE INDEX IF NOT EXISTS essay_document_versions
                    ON essay_runs(document_id, version_id);
            """)
        except sqlite3.Error:
            if hasattr(self, "connection"):
                self.connection.close()
            raise StoreUnavailableError from None

    @contextmanager
    def transaction(self) -> Generator[None]:
        """Serialize read-modify-write across threads and independent processes."""
        with self.lock:
            try:
                _ = self.connection.execute("BEGIN IMMEDIATE")
                with self.connection:
                    yield
            except (sqlite3.Error, ValidationError):
                raise StoreUnavailableError from None

    def execute(self, sql: str, values: tuple[SqlValue, ...] = ()) -> int:
        """Return affected rows for immutable conditional writes."""
        return self.connection.execute(sql, values).rowcount

    def records(self, suffix: str, values: tuple[SqlValue, ...] = ()) -> tuple[RunRecord, ...]:
        """Decode every stored row through the strict persisted-run contract."""
        rows = _TextRows.model_validate(
            self.connection.execute(SELECT_RUN + suffix, values).fetchall()
        )
        return tuple(RunRecord.model_validate_json(row[0]) for row in rows.root)

    def messages(self, thread_id: str) -> list[dict[str, str]]:
        """Preserve the legacy role/content dictionary return shape."""
        rows = _Messages.model_validate(
            self.connection.execute(
                "SELECT role, content FROM messages WHERE thread_id=? ORDER BY rowid", (thread_id,)
            ).fetchall()
        )
        return [{"role": role, "content": content} for role, content in rows.root]

    def close(self) -> None:
        """Close after callers have joined their active workers."""
        with self.lock:
            self.connection.close()
