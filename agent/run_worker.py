"""One graph execution and save-before-terminal path for JSON and SSE."""

import logging
from functools import partial

import anyio

from .api_models import run_error
from .contracts import EssayResult, FinalResult, ReviewControl, RunError, StoredParent
from .essay_llm import GenerationError
from .graph_state import EssayState, EssayUpdate
from .langgraph_boundary import CompiledGraph
from .previous_draft import PreviousDraft
from .revision_registry import final_revision
from .run_channels import Terminal
from .run_progress import ProgressSink, progress_scope
from .session_store import SqliteSessionStore
from .store_models import RunRecord, StoreConflictError, StoreUnavailableError

LOGGER = logging.getLogger(__name__)


def _result(state: EssayState) -> EssayResult:
    result = state.get("result")
    if result is None:
        code = "result_missing"
        raise RuntimeError(code)
    return result


class RunExecutor:
    """An app-scoped graph runs only per-request immutable input and local state."""

    def __init__(
        self, store: SqliteSessionStore, graph: CompiledGraph[EssayState, EssayUpdate]
    ) -> None:
        """Share resource owners, never result state or recovery context."""
        self.store: SqliteSessionStore = store
        self.graph: CompiledGraph[EssayState, EssayUpdate] = graph

    async def execute(self, record: RunRecord, sink: ProgressSink) -> Terminal:
        """Normalize known workflow failures and preserve an actual saved parent result."""
        previous: EssayResult | None = None
        try:
            parent = await anyio.to_thread.run_sync(self.store.parent, record.input)
            previous = parent.result if parent is not None else None
            state: EssayState = EssayState(
                request=record.input,
                evidence_version=record.evidence_version,
                revision_context=record.revision_context,
                repair_count=0,
                repair_log=(),
                technical_issues=(),
                usage=(),
                review_control=ReviewControl(stop=False, reason=None),
                stored_parent=None
                if previous is None
                else StoredParent(document_id=previous.document_id, version_id=previous.version_id),
                previous_draft=None
                if previous is None
                else PreviousDraft(
                    document_id=previous.document_id,
                    version_id=previous.version_id,
                    subtitle=previous.subtitle,
                    body=previous.body,
                ),
            )
            with progress_scope(sink):
                async for update in self.graph.astream(
                    state,
                    {"recursion_limit": 20, "run_name": "essay_request"},
                    stream_mode="updates",
                ):
                    for patch in update.values():
                        state = {**state, **patch}
            return await self._save(record, state, _result(state))
        except (
            GenerationError,
            RuntimeError,
            ValueError,
            TypeError,
            KeyError,
            OSError,
            StoreUnavailableError,
        ):
            error = run_error(
                record.input.request_id,
                "workflow_failed",
                "작성 처리 중 오류가 발생했습니다. 새 요청으로 다시 시도해 주세요.",
            )
            error = error.model_copy(update={"last_result": previous})
            try:
                await anyio.to_thread.run_sync(self.store.save_error, record, error)
            except (StoreUnavailableError, StoreConflictError):
                LOGGER.warning("Essay error persistence unavailable")
            return RunError(event="RunError", error=error)

    async def _save(self, record: RunRecord, state: EssayState, result: EssayResult) -> FinalResult:
        revision = final_revision(state)
        try:
            await anyio.to_thread.run_sync(
                partial(self.store.save_result, record, result, revision)
            )
        except (StoreUnavailableError, StoreConflictError):
            status = await anyio.to_thread.run_sync(self.store.reconcile_result, record, result)
        else:
            status = "stored"
        return FinalResult(event="FinalResult", result=result, persistence_status=status)
