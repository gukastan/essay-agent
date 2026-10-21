"""Typed dependencies injected into the existing supervisor graph."""

from dataclasses import dataclass
from typing import Protocol

from .essay_llm import EssayLLM
from .mcp_materials import CompanyMaterial


class EssayMaterials(Protocol):
    """The graph consumes current calls, never shared diagnostic history."""

    async def search_company_job_materials(
        self,
        company_name: str,
        job_title: str | None = None,
    ) -> tuple[CompanyMaterial, ...]:
        """Return bounded immutable material records from the current lookup."""
        ...

    async def writing_guide(self, question_type: str) -> str:
        """Read the discovered guide or the matching local policy."""
        ...

    async def writing_prompt(self, question_type: str) -> str:
        """Read the discovered procedure or the matching local policy."""
        ...


class SessionStore(Protocol):
    """The store remains lifespan-owned and unused by generation nodes."""

    def close(self) -> None:
        """Release the service-owned connection."""
        ...


@dataclass(frozen=True, slots=True)
class SupervisorDeps:
    """One service-owned pair of providers and optional shared resources."""

    fast_llm: EssayLLM
    quality_llm: EssayLLM
    mcp: EssayMaterials | None = None
    session_store: SessionStore | None = None
