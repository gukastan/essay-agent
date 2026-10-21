"""Serve public essay assets and relay the fixed backend API on one origin."""

from collections.abc import AsyncGenerator, AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Final
from uuid import UUID

import anyio
import httpx
import uvicorn
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, Response, StreamingResponse

PUBLIC_ASSETS: Final = frozenset(
    {"tokens.css", "components.js", "app.js", "api.js", "form.js", "result-view.js"}
)


@dataclass(frozen=True, slots=True)
class ProxySettings:
    """Only trusted startup configuration chooses the upstream and asset root."""

    backend: str = "http://127.0.0.1:8100"
    site_root: Path = Path(__file__).parent


def _public_file(root: Path, relative: str) -> FileResponse:
    target = root / relative
    if target.is_symlink() or not target.resolve().is_relative_to(root.resolve()):
        raise HTTPException(status_code=404)
    if not target.is_file():
        raise HTTPException(status_code=404)
    return FileResponse(target, headers={"X-Content-Type-Options": "nosniff"})


def _unavailable() -> JSONResponse:
    return JSONResponse(
        {
            "error": {
                "request_id": None,
                "generation_status": "technical_error",
                "code": "backend_unavailable",
                "message": "서버 연결을 확인한 뒤 다시 시도해 주세요.",
                "last_result": None,
            }
        },
        status_code=503,
    )


async def _relay(client: httpx.AsyncClient, request: Request) -> Response:
    upstream_request = client.build_request(
        request.method,
        request.url.path,
        params=tuple(request.query_params.multi_items()),
        content=await request.body(),
        headers={"Content-Type": "application/json"},
    )
    try:
        upstream = await client.send(upstream_request, stream=True)
    except httpx.RequestError:
        return _unavailable()
    headers = {
        key: value
        for key, value in upstream.headers.items()
        if key.lower() in {"content-type", "location", "cache-control", "x-request-id"}
    }
    headers["X-Accel-Buffering"] = "no"

    async def chunks() -> AsyncIterator[bytes]:
        try:
            async for chunk in upstream.aiter_bytes():
                yield chunk
        finally:
            with anyio.CancelScope(shield=True):
                await upstream.aclose()

    return StreamingResponse(chunks(), status_code=upstream.status_code, headers=headers)


def create_app(
    settings: ProxySettings | None = None,
    transport: httpx.AsyncBaseTransport | None = None,
) -> FastAPI:
    """Keep streaming responses open until their downstream reader releases them."""
    settings = settings or ProxySettings()
    client = httpx.AsyncClient(
        base_url=settings.backend,
        timeout=httpx.Timeout(connect=5, read=300, write=10, pool=10),
        transport=transport,
        follow_redirects=False,
        trust_env=False,
    )

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncGenerator[None]:
        async with client:
            yield

    application = FastAPI(title="Essay workspace", lifespan=lifespan)

    @application.get("/")
    async def index() -> FileResponse:
        return _public_file(settings.site_root, "web_chat.html")

    @application.get("/web_assets/{name}")
    async def asset(name: str) -> FileResponse:
        if name not in PUBLIC_ASSETS:
            raise HTTPException(status_code=404)
        return _public_file(settings.site_root, "web_assets/" + name)

    @application.get("/health")
    async def health(request: Request) -> Response:
        return await _relay(client, request)

    @application.post("/chat")
    @application.post("/chat/stream")
    async def chat(request: Request) -> Response:
        return await _relay(client, request)

    @application.get("/runs/{request_id}")
    async def run(request_id: UUID, request: Request) -> Response:
        del request_id
        return await _relay(client, request)

    @application.get("/documents/{document_id}/versions")
    async def versions(document_id: UUID, request: Request) -> Response:
        del document_id
        return await _relay(client, request)

    return application


app = create_app()

if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=8600, log_level="warning")
