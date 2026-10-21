from collections.abc import AsyncIterator
from pathlib import Path
from uuid import uuid4

import httpx
import pytest
from typing_extensions import override

from agent.api_models import ChatResponse, ErrorResponse, HealthResponse, RunLookup, VersionList
from agent.app_runtime import AppSettings
from agent.contracts import EssayRequest, FinalResult
from server import create_app as create_backend
from web_demo_server import ProxySettings, create_app


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.fixture
def public_site(tmp_path: Path) -> Path:
    root = tmp_path / "site"
    (root / "web_assets").mkdir(parents=True)
    _ = (root / "web_chat.html").write_text("<title>public</title>", encoding="utf-8")
    _ = (root / "web_assets" / "tokens.css").write_text(":root{}", encoding="utf-8")
    for name in (".env", ".gitignore", "server.py"):
        _ = (root / name).write_text("SENTINEL-NOT-A-REAL-SECRET", encoding="utf-8")
    return root


@pytest.fixture
async def service(tmp_path: Path, public_site: Path) -> AsyncIterator[httpx.AsyncClient]:
    backend = create_backend(
        AppSettings(backend="fake", db_path=tmp_path / "runs.db", mcp_enabled=False)
    )
    proxy = create_app(ProxySettings(site_root=public_site), httpx.ASGITransport(app=backend))
    async with (
        backend.router.lifespan_context(backend),
        proxy.router.lifespan_context(proxy),
        httpx.AsyncClient(
            transport=httpx.ASGITransport(app=proxy), base_url="http://proxy"
        ) as client,
    ):
        yield client


@pytest.mark.anyio
async def test_empty_request_when_proxied_returns_same_saved_result(
    service: httpx.AsyncClient,
) -> None:
    request = EssayRequest()
    response = await service.post("/chat", content=request.model_dump_json())
    assert response.status_code == 200
    result = ChatResponse.model_validate_json(response.content)
    lookup = await service.get(f"/runs/{request.request_id}")
    saved = RunLookup.model_validate_json(lookup.content)
    assert saved.result == result.result
    assert saved.input == request
    assert result.metadata.persistence_status == "stored"
    versions = VersionList.model_validate_json(
        (await service.get(f"/documents/{request.document_id}/versions")).content
    )
    assert versions.versions[0].request_id == request.request_id
    health = HealthResponse.model_validate_json((await service.get("/health")).content)
    assert health.llm_backend == "fake"


@pytest.mark.anyio
async def test_stream_when_posted_preserves_terminal_and_utf8(service: httpx.AsyncClient) -> None:
    request = EssayRequest(question="지원 동기를 작성해 주세요.")
    response = await service.post("/chat/stream", content=request.model_dump_json())
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    frames = [frame.removeprefix("data: ") for frame in response.text.split("\n\n") if frame]
    assert frames[-1] == "[DONE]"
    final = FinalResult.model_validate_json(frames[-2])
    assert final.result.request_id == request.request_id
    assert "\ufffd" not in final.result.body
    assert len(frames) == 14


@pytest.mark.anyio
@pytest.mark.parametrize("status", [422, 409, 503])
async def test_error_when_upstream_rejects_preserves_status_and_body(
    public_site: Path, status: int
) -> None:
    body = b'{"error":{"code":"rejected"}}'

    def upstream(request: httpx.Request) -> httpx.Response:
        assert request.method == "POST"
        assert request.content == b"{}"
        return httpx.Response(
            status,
            content=body,
            headers={"Content-Type": "application/json", "Location": "/runs/example"},
        )

    proxy = create_app(ProxySettings(site_root=public_site), httpx.MockTransport(upstream))
    async with (
        proxy.router.lifespan_context(proxy),
        httpx.AsyncClient(
            transport=httpx.ASGITransport(app=proxy), base_url="http://proxy"
        ) as client,
    ):
        response = await client.post("/chat/stream", content=b"{}")
    assert response.status_code == status
    assert response.content == body
    assert response.headers["location"] == "/runs/example"


@pytest.mark.anyio
async def test_get_when_query_repeats_preserves_query(public_site: Path) -> None:
    def upstream(request: httpx.Request) -> httpx.Response:
        assert request.url.query == b"tag=a&tag=b&text=%ED%95%9C%EA%B8%80"
        return httpx.Response(200, json={"status": "ok"})

    proxy = create_app(ProxySettings(site_root=public_site), httpx.MockTransport(upstream))
    async with (
        proxy.router.lifespan_context(proxy),
        httpx.AsyncClient(
            transport=httpx.ASGITransport(app=proxy), base_url="http://proxy"
        ) as client,
    ):
        response = await client.get("/health?tag=a&tag=b&text=%ED%95%9C%EA%B8%80")
    assert response.status_code == 200


@pytest.mark.anyio
@pytest.mark.parametrize(
    "path",
    [
        "/.env",
        "/.gitignore",
        "/server.py",
        "/web_assets/../.env",
        "/web_assets/%2e%2e/.env",
        "/web_assets/%252e%252e/.env",
        "/%2e%2e/.env",
        "/web_assets/showcase.html",
    ],
)
async def test_static_when_nonpublic_path_never_exposes_sentinel(
    public_site: Path, path: str
) -> None:
    proxy = create_app(ProxySettings(site_root=public_site))
    async with (
        proxy.router.lifespan_context(proxy),
        httpx.AsyncClient(
            transport=httpx.ASGITransport(app=proxy), base_url="http://proxy"
        ) as client,
    ):
        response = await client.get(path)
    assert response.status_code == 404
    assert "SENTINEL" not in response.text


@pytest.mark.anyio
async def test_static_when_allowed_asset_is_symlink_rejects(public_site: Path) -> None:
    (public_site / "web_assets" / "app.js").symlink_to(public_site / ".env")
    proxy = create_app(ProxySettings(site_root=public_site))
    async with (
        proxy.router.lifespan_context(proxy),
        httpx.AsyncClient(
            transport=httpx.ASGITransport(app=proxy), base_url="http://proxy"
        ) as client,
    ):
        response = await client.get("/web_assets/app.js")
    assert response.status_code == 404
    assert "SENTINEL" not in response.text


@pytest.mark.anyio
async def test_static_when_asset_parent_is_symlink_rejects(tmp_path: Path) -> None:
    root = tmp_path / "site"
    root.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    _ = (outside / "app.js").write_text("SENTINEL-NOT-A-REAL-SECRET", encoding="utf-8")
    (root / "web_assets").symlink_to(outside, target_is_directory=True)
    proxy = create_app(ProxySettings(site_root=root))
    async with (
        proxy.router.lifespan_context(proxy),
        httpx.AsyncClient(
            transport=httpx.ASGITransport(app=proxy), base_url="http://proxy"
        ) as client,
    ):
        response = await client.get("/web_assets/app.js")
    assert response.status_code == 404
    assert "SENTINEL" not in response.text


class TrackedStream(httpx.AsyncByteStream):
    closed: bool = False

    @override
    async def __aiter__(self) -> AsyncIterator[bytes]:
        yield b"data: [DONE]\n\n"

    @override
    async def aclose(self) -> None:
        self.closed = True


@pytest.mark.anyio
async def test_relay_when_stream_finishes_closes_upstream(public_site: Path) -> None:
    stream = TrackedStream()

    def upstream(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, stream=stream, headers={"Content-Type": "text/event-stream"})

    proxy = create_app(ProxySettings(site_root=public_site), httpx.MockTransport(upstream))
    async with (
        proxy.router.lifespan_context(proxy),
        httpx.AsyncClient(
            transport=httpx.ASGITransport(app=proxy), base_url="http://proxy"
        ) as client,
    ):
        response = await client.post("/chat/stream", content=b"{}")
    assert response.content == b"data: [DONE]\n\n"
    assert stream.closed


@pytest.mark.anyio
async def test_static_when_public_asset_exists_serves_it(service: httpx.AsyncClient) -> None:
    response = await service.get("/web_assets/tokens.css")
    assert response.status_code == 200
    assert response.text == ":root{}"
    assert response.headers["x-content-type-options"] == "nosniff"


@pytest.mark.anyio
async def test_connection_when_upstream_unreachable_is_safe_503(public_site: Path) -> None:
    def upstream(request: httpx.Request) -> httpx.Response:
        diagnostic = "SENTINEL-PRIVATE-DIAGNOSTIC"
        raise httpx.ConnectError(diagnostic, request=request)

    proxy = create_app(ProxySettings(site_root=public_site), httpx.MockTransport(upstream))
    async with (
        proxy.router.lifespan_context(proxy),
        httpx.AsyncClient(
            transport=httpx.ASGITransport(app=proxy), base_url="http://proxy"
        ) as client,
    ):
        response = await client.get(f"/runs/{uuid4()}")
    assert response.status_code == 503
    assert "SENTINEL" not in response.text
    assert ErrorResponse.model_validate_json(response.content).error.code == "backend_unavailable"
