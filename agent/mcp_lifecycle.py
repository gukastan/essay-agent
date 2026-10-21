"""Single-task ownership of MCP transports, bounded startup and deterministic teardown."""

import logging
import sys
from collections.abc import Mapping
from contextlib import AsyncExitStack
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Final

import anyio
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from mcp.shared.exceptions import MCPError
from pydantic import ValidationError

if TYPE_CHECKING:
    from anyio.abc import TaskGroup

MAX_TIMEOUT: Final = 8.0
LOGGER: Final = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class MCPTimeouts:
    """Timeout policy, with the product's eight-second hard upper bound."""

    startup: float = 8.0
    call: float = 8.0

    def __post_init__(self) -> None:
        """Reject policies that exceed the public bound."""
        if not 0 < self.startup <= MAX_TIMEOUT or not 0 < self.call <= MAX_TIMEOUT:
            message = "MCP timeouts must be positive and at most eight seconds"
            raise ValueError(message)


class MCPConnection:
    """Mutable connection owner; start and stop belong to the same lifespan task."""

    def __init__(self, scripts: Mapping[str, Path], timeouts: MCPTimeouts) -> None:
        """Keep process definitions without opening any resources."""
        self.scripts: Mapping[str, Path] = dict(scripts)
        self.timeouts: MCPTimeouts = timeouts
        self.sessions: dict[str, ClientSession] = {}
        self.warnings: list[str] = []
        self._group: TaskGroup | None = None
        self._owner: int | None = None
        self._ready: anyio.Event = anyio.Event()
        self._stop: anyio.Event = anyio.Event()

    def warn(self, code: str) -> None:
        """Record safe diagnostic codes without exposing source text or secrets."""
        self.warnings.append(code)
        LOGGER.warning("MCP fallback", extra={"mcp_code": code})

    async def start(self) -> None:
        """Start once; all session scopes live inside the lifecycle worker."""
        if self._group is not None:
            return
        self._owner = anyio.get_current_task().id
        self._ready = anyio.Event()
        self._stop = anyio.Event()
        self._group = anyio.create_task_group()
        _ = await self._group.__aenter__()
        _ = self._group.start_soon(self._run)
        with anyio.move_on_after(self.timeouts.startup) as startup:
            await self._ready.wait()
        if startup.cancelled_caught:
            self.sessions.clear()
            self.warn("startup_timeout")

    async def _run(self) -> None:
        """Unwind session and transport scopes in their original task, even on timeout."""
        try:
            with anyio.fail_after(self.timeouts.startup) as deadline:
                async with AsyncExitStack() as stack:
                    for name, script in self.scripts.items():
                        if not script.is_file():
                            raise FileNotFoundError(script)
                        params = StdioServerParameters(command=sys.executable, args=[str(script)])
                        read, write = await stack.enter_async_context(stdio_client(params))
                        session = await stack.enter_async_context(ClientSession(read, write))
                        _ = await session.initialize()
                        self.sessions[name] = session
                    deadline.deadline = float("inf")
                    self._ready.set()
                    await self._stop.wait()
        except* (
            OSError,
            ValidationError,
            TimeoutError,
            RuntimeError,
            MCPError,
            anyio.EndOfStream,
            anyio.BrokenResourceError,
            anyio.ClosedResourceError,
        ):
            self.warn("startup_or_transport_unavailable")
        finally:
            self.sessions.clear()
            self._ready.set()

    async def stop(self) -> None:
        """Join the worker without closing its AnyIO scopes from this task."""
        if self._group is None:
            return
        if anyio.get_current_task().id != self._owner:
            message = "MCP start and stop must run in the same lifespan task"
            raise RuntimeError(message)
        self._stop.set()
        _ = await self._group.__aexit__(None, None, None)
        self._group = None
        self._owner = None
