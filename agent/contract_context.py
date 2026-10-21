"""Public contract_context boundary contracts."""

from .contract_analysis import Analysis
from .contract_base import ContractModel, EvidenceVersion
from .contract_drafts import DraftBundle, IntegrationReport, SectionDraft, Sentence, WritingReport
from .contract_planning import Outline
from .contract_results import EssayResult
from .contract_review import RepairLogEntry, Review
from .contract_sources import EssayRequest, Fact, RevisionContext, SourceSnapshot, StoredParent


class ContractContext(ContractModel):
    """Immutable ContractContext payload."""

    evidence_version: EvidenceVersion
    fallback_provenance: tuple[Sentence, ...] = ()
    sources: tuple[SourceSnapshot, ...] = ()
    facts: tuple[Fact, ...] = ()
    analysis: Analysis | None = None
    outline: Outline | None = None
    section_drafts: tuple[SectionDraft, ...] = ()
    writing_report: WritingReport | None = None
    bundle: DraftBundle | None = None
    integration_report: IntegrationReport | None = None
    review: Review | None = None
    result: EssayResult | None = None
    repair_log: tuple[RepairLogEntry, ...] = ()
    request: EssayRequest | None = None
    parent: StoredParent | None = None
    revision_context: RevisionContext | None = None
