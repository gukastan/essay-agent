"""SQLite sessions and immutable essay versions with atomic request reservation."""

from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID, uuid4

from .contract_results import PersistenceStatus
from .contracts import (
    EssayRequest,
    EssayResult,
    EvidenceVersion,
    RevisionContext,
    RunErrorPayload,
)
from .request_normalization import (
    NormalizationBasis,
    fingerprint,
    normalize_request,
    restore_identity,
)
from .store_models import (
    Reservation,
    ReservationKind,
    RunRecord,
    StoreConflictError,
    StoreUnavailableError,
    duplicate_kind,
    result_matches,
    validate_revision_update,
)
from .store_sql import StoreDatabase

DB_PATH = Path(__file__).parent.parent / "session.db"


def _now() -> str:
    return datetime.now(UTC).isoformat()


class SqliteSessionStore:
    """Synchronous transactional primitives; async services use a worker thread."""

    def __init__(self, db_path: Path = DB_PATH) -> None:
        """Open the configured database without deleting existing messages."""
        self.database: StoreDatabase = StoreDatabase(db_path)

    def load(self, thread_id: str) -> list[dict[str, str]]:
        """Read the original messages API in insertion order."""
        with self.database.transaction():
            return self.database.messages(thread_id)

    def append(self, thread_id: str, role: str, content: str) -> None:
        """Append an original-format message without modifying essay versions."""
        with self.database.transaction():
            _ = self.database.execute(
                "INSERT INTO messages VALUES (?,?,?,?)", (thread_id, role, content, _now())
            )

    def close(self) -> None:
        """Release this lifespan-owned database connection."""
        self.database.close()

    def _get(self, request_id: UUID) -> RunRecord | None:
        rows = self.database.records(" WHERE request_id=?", (str(request_id),))
        return rows[0] if rows else None

    def get(self, request_id: UUID) -> RunRecord | None:
        """Return persisted state only; never regenerate or use a result cache."""
        with self.database.transaction():
            return self._get(request_id)

    def _parent(self, request: EssayRequest) -> RunRecord | None:
        if request.parent_version_id is None:
            return None
        rows = self.database.records(
            " WHERE version_id=? AND document_id=? AND status='completed'",
            (request.parent_version_id, str(request.document_id)),
        )
        if not rows:
            code = "parent_not_persisted_in_document"
            raise StoreConflictError(code)
        return rows[0]

    def parent(self, request: EssayRequest) -> RunRecord | None:
        """Load only a completed parent from the same document."""
        with self.database.transaction():
            return self._parent(request)

    def _ancestors(self, parent: RunRecord | None) -> tuple[EssayRequest, ...]:
        result: list[EssayRequest] = []
        seen: set[UUID] = set()
        current = parent
        while current is not None:
            if current.input.request_id in seen:
                code = "cyclic_lineage"
                raise StoreConflictError(code)
            seen.add(current.input.request_id)
            result.append(current.input)
            current = self._parent(current.input)
        return tuple(result)

    def reserve(self, request: EssayRequest) -> Reservation:
        """Atomically normalize identity and insert, or classify an existing run."""
        with self.database.transaction():
            existing = self._get(request.request_id)
            restored = restore_identity(request, existing)
            parent = self._parent(restored)
            evidence = existing.evidence_version if existing else EvidenceVersion(str(uuid4()))
            normalized = normalize_request(
                restored, NormalizationBasis(parent, existing, self._ancestors(parent)), evidence
            )
            request_hash = fingerprint(normalized.request)
            if existing is not None:
                if request_hash != existing.request_hash:
                    code = "request_hash_conflict"
                    raise StoreConflictError(code)
                return Reservation(kind=duplicate_kind(existing), record=existing)
            now = _now()
            record = RunRecord(
                request_hash=request_hash,
                status="running",
                input=normalized.request,
                evidence_version=evidence,
                revision_context=normalized.revision_context,
                result=None,
                error=None,
                created_at=now,
                updated_at=now,
            )
            self._insert(record)
            return Reservation(kind=ReservationKind.NEW, record=record)

    def _insert(self, record: RunRecord) -> None:
        request = record.input
        _ = self.database.execute(
            """INSERT INTO essay_runs
            (request_id,request_hash,thread_id,document_id,parent_version_id,
            evidence_version,status,input_json,revision_context_json,created_at,updated_at)
            VALUES (?,?,?,?,?,?,'running',?,?,?,?)""",
            (
                str(request.request_id),
                record.request_hash,
                str(request.thread_id),
                str(request.document_id),
                request.parent_version_id,
                record.evidence_version,
                request.model_dump_json(),
                record.revision_context.model_dump_json(),
                record.created_at,
                record.updated_at,
            ),
        )

    def versions(self, document_id: UUID) -> tuple[RunRecord, ...]:
        """List saved completed versions in deterministic creation order."""
        with self.database.transaction():
            return self.database.records(
                " WHERE document_id=? AND status='completed' ORDER BY created_at, request_id",
                (str(document_id),),
            )

    def save_result(
        self, record: RunRecord, result: EssayResult, revision: RevisionContext
    ) -> None:
        """Commit one result and final registry atomically; completed rows are immutable."""
        completed = RunRecord.model_validate(
            record.model_copy(
                update={
                    "status": "completed",
                    "result": result,
                    "revision_context": revision,
                    "error": None,
                    "updated_at": _now(),
                }
            ).model_dump()
        )
        with self.database.transaction():
            current = self._matching(record)
            if current.status == "completed":
                if (
                    not result_matches(current.result, result)
                    or current.revision_context != revision
                ):
                    code = "completed_version_immutable"
                    raise StoreConflictError(code)
                return
            if current.status != "running":
                code = "run_not_running"
                raise StoreConflictError(code)
            if self.database.records(" WHERE version_id=?", (result.version_id,)):
                code = "version_already_persisted"
                raise StoreConflictError(code)
            validate_revision_update(current.revision_context, revision)
            _ = self.database.execute(
                """UPDATE essay_runs SET status='completed',version_id=?,result_json=?,
                revision_context_json=?,updated_at=?
                WHERE request_id=? AND request_hash=? AND status='running'""",
                (
                    result.version_id,
                    result.model_dump_json(),
                    revision.model_dump_json(),
                    completed.updated_at,
                    str(record.input.request_id),
                    record.request_hash,
                ),
            )

    def _matching(self, record: RunRecord) -> RunRecord:
        current = self._get(record.input.request_id)
        if (
            current is None
            or current.request_hash != record.request_hash
            or current.input != record.input
            or current.evidence_version != record.evidence_version
        ):
            code = "reservation_not_found"
            raise StoreConflictError(code)
        return current

    def save_error(self, record: RunRecord, error: RunErrorPayload) -> None:
        """Persist a sanitized technical outcome without changing a completed version."""
        if error.request_id != record.input.request_id:
            code = "error_request_mismatch"
            raise StoreConflictError(code)
        with self.database.transaction():
            current = self._matching(record)
            if current.status != "running":
                if current.status == "failed" and current.error == error:
                    return
                code = "run_not_running"
                raise StoreConflictError(code)
            _ = self.database.execute(
                """UPDATE essay_runs SET status='failed',error_json=?,updated_at=?
                WHERE request_id=?""",
                (error.model_dump_json(), _now(), str(record.input.request_id)),
            )

    def interrupt_orphans(self, active: frozenset[UUID]) -> tuple[UUID, ...]:
        """Reconcile running rows with the service registry, without rerunning them."""
        with self.database.transaction():
            rows = self.database.records(" WHERE status='running'")
            interrupted: list[UUID] = []
            for record in rows:
                request_id = record.input.request_id
                if request_id in active:
                    continue
                error = RunErrorPayload(
                    request_id=request_id,
                    generation_status="technical_error",
                    code="interrupted",
                    message="실행이 중단되었습니다. 새 요청으로 다시 작성해 주세요.",
                    last_result=None,
                )
                _ = self.database.execute(
                    """UPDATE essay_runs SET status='interrupted',error_json=?,updated_at=?
                    WHERE request_id=? AND status='running'""",
                    (error.model_dump_json(), _now(), str(request_id)),
                )
                interrupted.append(request_id)
            return tuple(interrupted)

    def reconcile_result(self, record: RunRecord, result: EssayResult) -> PersistenceStatus:
        """Read after an uncertain save; never retry generation or claim unproven storage."""
        try:
            saved = self.get(record.input.request_id)
        except StoreUnavailableError:
            return "unknown"
        if (
            saved is not None
            and saved.request_hash == record.request_hash
            and result_matches(saved.result, result)
        ):
            return "stored"
        return "failed"
