"""Server-loaded wording reference, deliberately without evidence identifiers."""

from uuid import UUID

from .contracts import ContractModel, VersionId


class PreviousDraft(ContractModel):
    """Preserve prior generated wording without promoting it to personal evidence."""

    document_id: UUID
    version_id: VersionId
    subtitle: str
    body: str
