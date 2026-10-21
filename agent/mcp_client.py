"""Bounded essay MCP access with discovery and shared local policy fallbacks."""

from collections.abc import Awaitable, Callable, Mapping
from pathlib import Path
from typing import Final, TypeVar

import anyio
from mcp import ClientSession
from mcp.shared.exceptions import MCPError
from mcp.types import Prompt, ResourceTemplate, Tool
from pydantic import ValidationError

from .mcp_lifecycle import MCPConnection, MCPTimeouts
from .mcp_materials import CompanyMaterial, MaterialResult, local_guide, local_prompt
from .mcp_wire import PromptPayload, ResourcePayload, ToolPayload

SERVER_DIR: Final = Path(__file__).resolve().parent.parent
DEFAULT_SERVER_SCRIPTS: Final = {"essay": SERVER_DIR / "mcp_server.py"}
DEFAULT_TIMEOUTS: Final = MCPTimeouts()
T = TypeVar("T")


class MCPClient(MCPConnection):
    """Mutable shared session client, owned by a single application lifespan task."""

    def __init__(
        self,
        server_scripts: Mapping[str, Path] | None = None,
        timeouts: MCPTimeouts = DEFAULT_TIMEOUTS,
    ) -> None:
        """Default only to the essay server, without simulated tool failures."""
        super().__init__(
            DEFAULT_SERVER_SCRIPTS if server_scripts is None else server_scripts,
            timeouts,
        )
        self._lock: anyio.Lock = anyio.Lock()

    async def _request(
        self, server: str, operation: Callable[[ClientSession], Awaitable[T]]
    ) -> T | None:
        """Bound queue waiting and SDK work together, returning a safe unavailable value."""
        session = self.sessions.get(server)
        if session is None:
            self.warn("unavailable")
            return None
        try:
            with anyio.fail_after(self.timeouts.call):
                async with self._lock:
                    return await operation(session)
        except (
            TimeoutError,
            RuntimeError,
            MCPError,
            OSError,
            anyio.EndOfStream,
            anyio.ClosedResourceError,
            anyio.BrokenResourceError,
            ValidationError,
        ):
            self.warn("capability_unavailable")
            return None

    async def search_company_job_materials(
        self,
        company_name: str,
        job_title: str | None = None,
    ) -> tuple[CompanyMaterial, ...]:
        """Return at most three frozen material records; lookup failure is nonfatal."""
        result = await self._request(
            "essay",
            lambda session: session.call_tool(
                "search_company_job_materials",
                {"company_name": company_name, "job_title": job_title},
            ),
        )
        if result is None:
            return ()
        try:
            envelope = ToolPayload.model_validate_json(result.model_dump_json())
            if envelope.is_error:
                self.warn("tool_error")
                return ()
            return MaterialResult.model_validate_json(envelope.text()).materials
        except ValueError:
            self.warn("invalid_tool_content")
            return ()

    async def list_tools(self, server: str = "essay") -> list[Tool]:
        """Discover tools through the live session."""
        result = await self._request(server, lambda session: session.list_tools())
        return [] if result is None else result.tools

    async def list_resource_templates(self, server: str = "essay") -> list[ResourceTemplate]:
        """Discover parameterized resources through the live session."""
        result = await self._request(server, lambda session: session.list_resource_templates())
        return [] if result is None else result.resource_templates

    async def find_resource_template(self, template_name: str) -> tuple[str, str] | None:
        """Return the discovered server and URI template, when available."""
        for server_name in tuple(self.sessions):
            for template in await self.list_resource_templates(server_name):
                if template.name == template_name:
                    return server_name, template.uri_template
        self.warn("resource_not_discovered")
        return None

    async def read_resource(self, uri: str, server: str = "essay") -> str | None:
        """Read textual resource blocks without assuming a nonempty first item."""
        result = await self._request(server, lambda session: session.read_resource(uri))
        if result is None:
            return None
        try:
            return ResourcePayload.model_validate_json(result.model_dump_json()).text()
        except ValueError:
            self.warn("invalid_resource_content")
            return None

    async def list_prompts(self, server: str = "essay") -> list[Prompt]:
        """Discover prompt definitions through the live session."""
        result = await self._request(server, lambda session: session.list_prompts())
        return [] if result is None else result.prompts

    async def find_prompt(self, prompt_name: str) -> str | None:
        """Return the server exposing the requested prompt."""
        for server_name in tuple(self.sessions):
            if any(prompt.name == prompt_name for prompt in await self.list_prompts(server_name)):
                return server_name
        self.warn("prompt_not_discovered")
        return None

    async def get_prompt(self, question_type: str, server: str = "essay") -> str | None:
        """Read the essay prompt from a discovered server."""
        result = await self._request(
            server,
            lambda session: session.get_prompt(
                "essay_writing_prompt",
                {"question_type": question_type},
            ),
        )
        if result is None:
            return None
        try:
            return PromptPayload.model_validate_json(result.model_dump_json()).text()
        except ValueError:
            self.warn("invalid_prompt_content")
            return None

    async def writing_guide(self, question_type: str) -> str:
        """Discover then read the guide, falling back to the same static file."""
        fallback = await anyio.to_thread.run_sync(local_guide, question_type)
        location = await self.find_resource_template("get_writing_guide")
        if location is None:
            return fallback
        server, template = location
        content = await self.read_resource(
            template.replace("{question_type}", question_type), server
        )
        return content or fallback

    async def writing_prompt(self, question_type: str) -> str:
        """Discover then read the writing prompt, preserving policy on failure."""
        fallback = await anyio.to_thread.run_sync(local_prompt, question_type)
        server = await self.find_prompt("essay_writing_prompt")
        if server is None:
            return fallback
        content = await self.get_prompt(question_type, server)
        return content or fallback
