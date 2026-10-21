"""Per-run safe progress observation at actual graph node boundaries."""

from collections.abc import Awaitable, Callable, Generator
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Final, Protocol, TypeAlias

from .contracts import StageCompleted, StageStarted
from .graph_state import EssayState, EssayUpdate

Node: TypeAlias = Callable[[EssayState], Awaitable[EssayUpdate]]
StageEvent: TypeAlias = StageStarted | StageCompleted


class ProgressSink(Protocol):
    """Nonblocking observer; disconnected consumers must not interrupt generation."""

    def __call__(self, event: StageEvent, /) -> None:
        """Publish only safe stage metadata without waiting for a consumer."""
        ...


_SINK: Final = ContextVar[ProgressSink | None]("essay_progress_sink", default=None)
_STAGES: Final = {
    "analyze_context": 1,
    "plan_structure": 2,
    "write_sections": 3,
    "integrate_draft": 4,
    "title_and_review": 5,
    "repair_draft": 5,
    "deliver_result": 6,
}


@contextmanager
def progress_scope(sink: ProgressSink) -> Generator[None]:
    """Bind one worker's observer and reset it even on error or cancellation."""
    token = _SINK.set(sink)
    try:
        yield
    finally:
        _SINK.reset(token)


def observe_node(name: str, node: Node) -> Node:
    """Wrap execution without changing graph state, routing or exception semantics."""
    stage = _STAGES[name]

    async def observed(state: EssayState) -> EssayUpdate:
        sink = _SINK.get()
        count = min(2, state.get("repair_count", 0) + (1 if name == "repair_draft" else 0))
        if sink is not None:
            sink(
                StageStarted(
                    event="StageStarted",
                    request_id=state["request"].request_id,
                    stage=stage,
                    repair_count=count,
                )
            )
        update = await node(state)
        if sink is not None:
            sink(
                StageCompleted(
                    event="StageCompleted",
                    request_id=state["request"].request_id,
                    stage=stage,
                    repair_count=update.get("repair_count", count),
                )
            )
        return update

    return observed
