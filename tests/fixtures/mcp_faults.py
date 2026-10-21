"""Explicit faulty peer for real stdio failure and cleanup scenarios."""

from typing import Literal, assert_never

import anyio
from fastmcp import FastMCP
from fastmcp.tools.base import ToolResult
from mcp.types import ImageContent, TextContent

Fault = Literal["error", "empty", "nontext", "malformed", "timeout", "schema"]


def create_fault_server(fault: Fault) -> FastMCP:
    """Inject faults at the public MCP capability boundary, not the client internals."""
    server = FastMCP("fault-fixture")

    @server.tool(
        name="search_company_job_materials",
        output_schema={"type": "object", "required": ["materials"]} if fault == "schema" else None,
    )
    async def materials(company_name: str, job_title: str | None = None) -> ToolResult:
        """Produce the selected deterministic peer failure."""
        _ = company_name, job_title
        match fault:
            case "error":
                return ToolResult(content=[TextContent(type="text", text="fault")], is_error=True)
            case "empty":
                return ToolResult(content=[])
            case "nontext":
                return ToolResult(
                    content=[ImageContent(type="image", data="AA==", mime_type="image/png")]
                )
            case "malformed":
                return ToolResult(content=[TextContent(type="text", text="{broken")])
            case "schema":
                return ToolResult(content="{}", structured_content={})
            case "timeout":
                await anyio.sleep_forever()
                return ToolResult(content=[])
            case _:
                assert_never(fault)

    @server.resource("writing-guide://essay/{question_type}", name="get_writing_guide")
    def guide(question_type: str) -> str:
        """Produce an empty resource for local fallback."""
        _ = question_type
        return ""

    @server.prompt(name="essay_writing_prompt")
    def prompt(question_type: str) -> str:
        """Produce an explicit prompt failure for local fallback."""
        message = f"Injected fixture failure: {question_type}"
        raise RuntimeError(message)

    return server
