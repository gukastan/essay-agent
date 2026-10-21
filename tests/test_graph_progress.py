from pathlib import Path
from uuid import uuid4

import anyio
import pytest

from agent.contracts import ContractViolation
from agent.graph_state import EssayState, EssayUpdate
from agent.run_progress import StageEvent, observe_node, progress_scope
from tests.analysis_support import request_for, seed
from tests.review_graph_support import Cycles, execute_graph


def save_events(name: str, events: list[StageEvent]) -> None:
    path = Path("../.omo/evidence/essay-agent/task-7-progress") / (name + ".json")
    path.parent.mkdir(parents=True, exist_ok=True)
    _ = path.write_text("[\n" + ",\n".join(e.model_dump_json() for e in events) + "\n]")


@pytest.mark.parametrize("repairs", [0, 1, 2])
def test_actual_node_progress_pairs_follow_bounded_graph(repairs: int) -> None:
    events: list[StageEvent] = []
    script = Cycles(repairs)

    async def run() -> None:
        with progress_scope(events.append):
            final, trace = await execute_graph(request_for(), script)
        expected = [1, 2, 3, 4, 5, *([5, 5] * repairs), 6]
        assert len(trace) == len(expected) == 6 + 2 * repairs
        assert [event.stage for event in events[::2]] == expected
        assert len(events) == 2 * len(trace)
        for started, completed in zip(events[::2], events[1::2], strict=True):
            assert started.event == "StageStarted"
            assert completed.event == "StageCompleted"
            assert started.stage == completed.stage
            assert started.repair_count == completed.repair_count
            assert started.request_id == completed.request_id == final.request.request_id
        assert [event.repair_count for event in events[::2]] == (
            [0] * 5 + [count for count in range(1, repairs + 1) for _ in range(2)] + [repairs]
        )
        assert len(script.calls) == 5 + 2 * repairs
        assert "deliver_result" not in script.calls

    anyio.run(run)
    save_events(f"repair-{repairs}", events)


def test_wrapper_preserves_error_identity_and_resets_observer() -> None:
    events: list[StageEvent] = []
    failure = ContractViolation("probe", "Deliberate node failure")

    async def failing(_state: EssayState) -> EssayUpdate:
        assert len(events) == 1
        raise failure

    async def success(_state: EssayState) -> EssayUpdate:
        return EssayUpdate()

    async def run() -> None:
        with (
            pytest.raises(ContractViolation) as caught,
            progress_scope(events.append),
        ):
            _ = await observe_node("write_sections", failing)(seed(request_for()))
        assert caught.value is failure
        _ = await observe_node("deliver_result", success)(seed(request_for()))
        assert len(events) == 1
        assert events[0].event == "StageStarted"

    anyio.run(run)
    save_events("error", events)


def test_wrapper_propagates_cancellation_without_completed_event() -> None:
    events: list[StageEvent] = []

    async def cancelled(_state: EssayState) -> EssayUpdate:
        await anyio.sleep_forever()
        return EssayUpdate()

    async def run() -> None:
        with progress_scope(events.append), anyio.CancelScope() as scope:
            scope.cancel()
            _ = await observe_node("repair_draft", cancelled)(seed(request_for()))
        assert scope.cancelled_caught
        assert len(events) == 1
        assert events[0].event == "StageStarted"
        assert events[0].repair_count == 1

    anyio.run(run)
    save_events("cancellation", events)


def test_concurrent_graph_workers_isolate_progress_context() -> None:
    first: list[StageEvent] = []
    second: list[StageEvent] = []
    identifiers = (uuid4(), uuid4())

    async def worker(index: int, events: list[StageEvent]) -> None:
        request = request_for().model_copy(update={"request_id": identifiers[index]})
        with progress_scope(events.append):
            _ = await execute_graph(request, Cycles(index))
        assert all(event.request_id == identifiers[index] for event in events)
        assert len(events) == 12 + 4 * index

    async def run() -> None:
        async with anyio.create_task_group() as group:
            _ = group.start_soon(worker, 0, first)
            _ = group.start_soon(worker, 1, second)

    anyio.run(run)
    save_events("concurrent-first", first)
    save_events("concurrent-second", second)
