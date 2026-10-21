from collections.abc import Generator
from pathlib import Path

import pytest

from agent.session_store import SqliteSessionStore


@pytest.fixture
def store(tmp_path: Path) -> Generator[SqliteSessionStore]:
    value = SqliteSessionStore(tmp_path / "test.db")
    try:
        yield value
    finally:
        value.close()
