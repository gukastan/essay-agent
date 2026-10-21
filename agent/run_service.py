"""Single-process admission, independent workers, persisted lookup and reconciliation."""

import logging
from typing import TYPE_CHECKING
from uuid import UUID

import anyio
from anyio.abc import TaskGroup

from .api_models import RunLookup, ServiceError, VersionList, VersionSummary, run_error
from .contracts import EssayRequest, FinalResult, RunError
from .run_channels import RunHandle
from .run_worker import RunExecutor
from .store_models import ReservationKind, RunRecord, StoreConflictError, StoreUnavailableError

LOGGER = logging.getLogger(__name__)

if TYPE_CHECKING:
    from .session_store import SqliteSessionStore


class RunService:
    """Serialize admission with active registration while generation runs independently."""

    def __init__(self, executor: RunExecutor, group: TaskGroup) -> None:
        """Use a lifespan task group; response cancellation never owns its workers."""
        self.executor: RunExecutor = executor
        self.store: SqliteSessionStore = executor.store
        self.group: TaskGroup = group
        self.lock: anyio.Lock = anyio.Lock()
        self.active: dict[UUID, RunHandle] = {}
        self.accepting: bool = True

    async def _reconcile(self) -> None:
        _ = await anyio.to_thread.run_sync(self.store.interrupt_orphans, frozenset(self.active))

    async def submit(self, request: EssayRequest) -> RunHandle:
        """Finish schema/identity/storage admission before a response stream opens."""
        async with self.lock:
            if not self.accepting:
                raise ServiceError(
                    503, run_error(request.request_id, "shutting_down", "서버가 종료 중입니다.")
                )
            try:
                await self._reconcile()
                reservation = await anyio.to_thread.run_sync(self.store.reserve, request)
            except StoreUnavailableError:
                raise ServiceError(
                    503,
                    run_error(
                        request.request_id, "storage_unavailable", "저장소에 연결할 수 없습니다."
                    ),
                ) from None
            except StoreConflictError as error:
                raise ServiceError(
                    409,
                    run_error(
                        request.request_id,
                        error.code,
                        "같은 요청 ID의 내용 또는 이전 버전이 일치하지 않습니다.",
                    ),
                ) from None
            record = reservation.record
            handle = RunHandle()
            if reservation.kind == ReservationKind.REPLAY and record.result is not None:
                handle.finish(
                    FinalResult(
                        event="FinalResult", result=record.result, persistence_status="stored"
                    )
                )
                return handle
            if reservation.kind != ReservationKind.NEW:
                handle.receive.close()
                handle.send.close()
                error = record.error or run_error(
                    request.request_id,
                    "already_running",
                    "작성 중입니다. 실행 조회로 결과를 확인해 주세요.",
                )
                raise ServiceError(409, error, f"/runs/{request.request_id}")
            self.active[request.request_id] = handle
            _ = self.group.start_soon(self._run, record, handle)
            return handle

    async def _run(self, record: RunRecord, handle: RunHandle) -> None:
        try:
            terminal = await self.executor.execute(record, handle.publish)
            handle.finish(terminal)
        finally:
            with anyio.CancelScope(shield=True):
                async with self.lock:
                    _ = self.active.pop(record.input.request_id, None)
                    if handle.terminal is None:
                        handle.finish(
                            RunError(
                                event="RunError",
                                error=run_error(
                                    record.input.request_id,
                                    "interrupted",
                                    "실행이 중단되었습니다. 새 요청으로 다시 작성해 주세요.",
                                ),
                            )
                        )
                    try:
                        await self._reconcile()
                    except StoreUnavailableError:
                        LOGGER.warning("Essay orphan reconciliation unavailable")

    async def lookup(self, request_id: UUID) -> RunLookup:
        """Reconcile orphan running state before returning the persisted form and result."""
        async with self.lock:
            try:
                await self._reconcile()
                record = await anyio.to_thread.run_sync(self.store.get, request_id)
            except StoreUnavailableError:
                raise ServiceError(
                    503,
                    run_error(request_id, "storage_unavailable", "저장소에 연결할 수 없습니다."),
                ) from None
        if record is None:
            raise ServiceError(
                404, run_error(request_id, "run_not_found", "실행을 찾을 수 없습니다.")
            )
        return RunLookup(
            request_id=request_id,
            status=record.status,
            result=record.result,
            error=record.error,
            persistence_status="pending" if record.status == "running" else "stored",
            input=record.input,
        )

    async def versions(self, document_id: UUID) -> VersionList:
        """List completed persisted versions without invoking the graph."""
        try:
            records = await anyio.to_thread.run_sync(self.store.versions, document_id)
        except StoreUnavailableError:
            raise ServiceError(
                503, run_error(None, "storage_unavailable", "저장소에 연결할 수 없습니다.")
            ) from None
        return VersionList(
            document_id=document_id,
            versions=tuple(
                VersionSummary(
                    request_id=record.input.request_id,
                    version_id=record.result.version_id,
                    created_at=record.created_at,
                    generation_status=record.result.generation_status,
                )
                for record in records
                if record.result is not None
            ),
        )

    async def shutdown(self) -> None:
        """Stop admission and bound worker grace before cancelling unfinished runs."""
        async with self.lock:
            self.accepting = False
            handles = tuple(self.active.values())
        with anyio.move_on_after(5):
            for handle in handles:
                await handle.done.wait()
        self.group.cancel_scope.cancel()
