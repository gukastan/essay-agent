"""Bounded response subscriptions independent of generation-task lifetime."""

from collections.abc import AsyncIterator
from typing import TYPE_CHECKING, TypeAlias

import anyio

from .contracts import FinalResult, RunError
from .run_progress import StageEvent

if TYPE_CHECKING:
    from anyio.streams.memory import MemoryObjectReceiveStream, MemoryObjectSendStream

Terminal: TypeAlias = FinalResult | RunError
RunEvent: TypeAlias = StageEvent | Terminal


class RunHandle:
    """One waiting response holds its outcome; finished runs are not cached globally."""

    def __init__(self) -> None:
        """Allow32 events: above the bounded10-node graph's21-event maximum."""
        send, receive = anyio.create_memory_object_stream[RunEvent](32)
        self.send: MemoryObjectSendStream[RunEvent] = send
        self.receive: MemoryObjectReceiveStream[RunEvent] = receive
        self.done: anyio.Event = anyio.Event()
        self.terminal: Terminal | None = None
        self.connected: bool = True

    def publish(self, event: RunEvent) -> None:
        """Never block a worker behind a slow or disconnected HTTP reader."""
        if not self.connected:
            return
        try:
            self.send.send_nowait(event)
        except (anyio.WouldBlock, anyio.BrokenResourceError, anyio.ClosedResourceError):
            self.connected = False
            self.send.close()

    def finish(self, terminal: Terminal) -> None:
        """Publish one terminal only after persistence has been attempted."""
        if self.terminal is not None:
            code = "duplicate_terminal"
            raise RuntimeError(code)
        self.terminal = terminal
        self.publish(terminal)
        self.send.close()
        self.done.set()

    async def wait(self) -> Terminal:
        """Keep generation alive if the JSON caller is cancelled."""
        try:
            await self.done.wait()
            if self.terminal is None:
                code = "missing_terminal"
                raise RuntimeError(code)
            return self.terminal
        finally:
            self.receive.close()
            self.connected = False

    async def events(self) -> AsyncIterator[RunEvent]:
        """Close only this subscription when a stream client disconnects."""
        try:
            async for event in self.receive:
                yield event
        finally:
            self.receive.close()
            self.connected = False
