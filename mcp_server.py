"""Essay-only MCP capabilities backed by registered local documents."""

from pathlib import Path
from typing import Final

from fastmcp import FastMCP

from agent.mcp_materials import DATA_DIR, MaterialResult, local_guide, local_prompt, search_catalog


def create_server(reference_root: Path = DATA_DIR / "references") -> FastMCP:
    """Build the product server; tests can supply a fictional temporary catalog."""
    server = FastMCP(name="essay")

    @server.tool(name="search_company_job_materials")
    def search_company_job_materials(
        company_name: str,
        job_title: str | None = None,
    ) -> MaterialResult:
        """Return registered local company/job texts, never live search results."""
        return search_catalog(reference_root, company_name, job_title)

    @server.resource("writing-guide://essay/{question_type}", name="get_writing_guide")
    def get_writing_guide(question_type: str) -> str:
        """Return a writing approach, not a company's evaluation criteria."""
        return local_guide(question_type)

    @server.prompt(name="essay_writing_prompt")
    def essay_writing_prompt(question_type: str) -> str:
        """Return only static procedure and the matching writing guide."""
        return local_prompt(question_type)

    return server


mcp: Final = create_server()

if __name__ == "__main__":
    mcp.run(transport="stdio", show_banner=False)
