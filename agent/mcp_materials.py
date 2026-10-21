"""Registered local reference data and shared static writing policies."""

from pathlib import Path
from typing import Annotated, Final, Literal
from unicodedata import normalize

from pydantic import Field, TypeAdapter

from .contract_base import ContractModel, ContractViolationError, EvidenceVersion, SourceId
from .contract_sources import CatalogSourceMetadata, SourceMetadata, SourceSnapshot

DATA_DIR: Final = Path(__file__).resolve().parent.parent / "data"
QuestionType = Literal["experience", "motivation", "strength", "aspiration", "general"]
QUESTION_TYPE: Final = TypeAdapter(QuestionType)
NonemptyText = Annotated[str, Field(min_length=1, strict=True)]


class CatalogEntry(ContractModel):
    """Registered metadata; URLs are attribution only and never fetched."""

    source_id: NonemptyText
    company: NonemptyText
    job_title: NonemptyText | None
    title: NonemptyText
    relative_path: NonemptyText
    source_url: str | None
    registered_at: NonemptyText
    published_at: str | None


class CompanyMaterial(CatalogEntry):
    """Immutable text copied from a registered file at lookup time."""

    text: NonemptyText

    def snapshot(self, evidence_version: EvidenceVersion, source_order: int) -> SourceSnapshot:
        """Freeze current text and attribution without re-reading any source file."""
        return SourceSnapshot(
            source_id=SourceId(f"mcp:essay:{self.source_id}"),
            evidence_version=evidence_version,
            source_kind="job_posting" if self.job_title else "company",
            text=self.text,
            source_order=source_order,
            metadata=SourceMetadata(
                origin="mcp",
                label=self.title,
                uri=self.source_url,
                catalog=CatalogSourceMetadata(
                    source_id=self.source_id,
                    company=self.company,
                    job_title=self.job_title,
                    relative_path=self.relative_path,
                    registered_at=self.registered_at,
                    published_at=self.published_at,
                ),
            ),
        )


class MaterialResult(ContractModel):
    """Typed MCP tool response."""

    materials: tuple[CompanyMaterial, ...] = Field(max_length=3)


CATALOG: Final = TypeAdapter(tuple[CatalogEntry, ...])


def canonical_name(value: str) -> str:
    """Normalize names without substring, alias, or fuzzy matching."""
    return " ".join(normalize("NFC", value).split()).casefold()


def reference_path(root: Path, relative_path: str) -> Path:
    """Reject absolute paths, traversal and symlink escapes before reading."""
    relative = Path(relative_path)
    candidate = (root / relative).resolve()
    if (
        relative.is_absolute()
        or ".." in relative.parts
        or not candidate.is_relative_to(root.resolve())
    ):
        msg = "reference_path"
        raise ContractViolationError(msg, "Reference must remain under catalog root")
    if candidate.suffix.lower() not in {".txt", ".md"} or not candidate.is_file():
        msg = "reference_file"
        raise ContractViolationError(msg, "Reference must be an existing text file")
    return candidate


def search_catalog(root: Path, company_name: str, job_title: str | None) -> MaterialResult:
    """Read at most three registered documents for an unambiguous exact company."""
    catalog_path = root / "catalog.json"
    if not catalog_path.resolve().is_relative_to(root.resolve()):
        msg = "catalog_path"
        raise ContractViolationError(msg, "Catalog must remain under reference root")
    entries = CATALOG.validate_json(catalog_path.read_bytes())
    company_key = canonical_name(company_name)
    matches = [entry for entry in entries if canonical_name(entry.company) == company_key]
    # Casefold may conflate distinct spellings (for example Straße and Strasse).
    identities = {" ".join(normalize("NFC", entry.company).split()).lower() for entry in matches}
    if not company_key or len(identities) != 1:
        return MaterialResult(materials=())
    source_ids = [entry.source_id for entry in matches]
    if len(source_ids) != len(set(source_ids)):
        return MaterialResult(materials=())
    role = canonical_name(job_title or "")
    eligible = [
        entry
        for entry in matches
        if not role or entry.job_title is None or canonical_name(entry.job_title) == role
    ]
    eligible.sort(
        key=lambda entry: (
            not bool(role and entry.job_title and canonical_name(entry.job_title) == role),
            entry.source_id,
        )
    )
    materials = tuple(
        CompanyMaterial(
            source_id=entry.source_id,
            company=entry.company,
            job_title=entry.job_title,
            title=entry.title,
            relative_path=entry.relative_path,
            source_url=entry.source_url,
            registered_at=entry.registered_at,
            published_at=entry.published_at,
            text=reference_path(root, entry.relative_path).read_text(encoding="utf-8"),
        )
        for entry in eligible[:3]
    )
    return MaterialResult(materials=materials)


def local_guide(question_type: str) -> str:
    """Read only one of the five policy guides, shared with MCP fallback."""
    selected = QUESTION_TYPE.validate_python(question_type)
    return (DATA_DIR / "writing_guides" / f"{selected}.md").read_text(encoding="utf-8")


def local_prompt(question_type: str) -> str:
    """Compose static policy separately from caller supplied source material."""
    guide = local_guide(question_type)
    procedure = (DATA_DIR / "writing_guides" / "procedure.md").read_text(encoding="utf-8")
    return f"{procedure}\n\n{guide}"
