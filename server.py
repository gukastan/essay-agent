"""FastAPI essay API with one lifespan and a shared JSON/SSE execution path."""

from collections.abc import AsyncIterator
from uuid import UUID

import uvicorn
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, ValidationError
from starlette.exceptions import HTTPException

from agent.api_models import (
    ChatResponse,
    ErrorResponse,
    HealthResponse,
    RunLookup,
    ServiceError,
    VersionList,
    run_error,
)
from agent.app_runtime import ApplicationRuntime, AppSettings, RuntimeFactories
from agent.contracts import EssayRequest, FinalResult, ResponseMetadata
from agent.run_channels import RunHandle


class _RequestIdentity(BaseModel):
    request_id: UUID | None = None


def _error_response(error: ServiceError) -> JSONResponse:
    headers = {"Location": error.location} if error.location else None
    return JSONResponse(
        ErrorResponse(error=error.error).model_dump(mode="json"),
        status_code=error.status,
        headers=headers,
    )


async def _service_error(request: Request, error: Exception) -> JSONResponse:
    del request
    if isinstance(error, ServiceError):
        return _error_response(error)
    return _error_response(
        ServiceError(500, run_error(None, "internal_error", "처리 오류가 발생했습니다."))
    )


async def _validation_error(request: Request, error: Exception) -> JSONResponse:
    del error
    try:
        request_id = _RequestIdentity.model_validate_json(await request.body()).request_id
    except ValidationError:
        request_id = None
    return _error_response(
        ServiceError(422, run_error(request_id, "invalid_request", "요청 형식을 확인해 주세요."))
    )


async def _http_error(request: Request, error: Exception) -> JSONResponse:
    del request
    return _error_response(
        ServiceError(
            error.status_code if isinstance(error, HTTPException) else 500,
            run_error(None, "http_error", "요청 경로 또는 방식을 확인해 주세요."),
        )
    )


async def _events(handle: RunHandle) -> AsyncIterator[str]:
    async for event in handle.events():
        yield f"data: {event.model_dump_json()}\n\n"
    yield "data: [DONE]\n\n"


def create_app(
    settings: AppSettings | None = None, factories: RuntimeFactories | None = None
) -> FastAPI:
    """Create isolated test applications or the configured production lifespan."""
    runtime = ApplicationRuntime(settings, factories or RuntimeFactories())
    application = FastAPI(title="Essay Agent", lifespan=runtime.lifespan)
    application.add_exception_handler(ServiceError, _service_error)
    application.add_exception_handler(RequestValidationError, _validation_error)
    application.add_exception_handler(HTTPException, _http_error)

    @application.get("/health")
    async def health() -> HealthResponse:
        return runtime.health()

    @application.post("/chat")
    async def chat(request: EssayRequest) -> ChatResponse:
        handle = await runtime.require_service().submit(request)
        terminal = await handle.wait()
        if isinstance(terminal, FinalResult):
            return ChatResponse(
                result=terminal.result,
                metadata=ResponseMetadata(persistence_status=terminal.persistence_status),
            )
        raise ServiceError(500, terminal.error)

    @application.post("/chat/stream")
    async def chat_stream(request: EssayRequest) -> StreamingResponse:
        handle = await runtime.require_service().submit(request)
        return StreamingResponse(
            _events(handle),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "X-Accel-Buffering": "no",
                "X-Request-ID": str(request.request_id),
            },
        )

    @application.get("/runs/{request_id}")
    async def lookup(request_id: UUID) -> RunLookup:
        return await runtime.require_service().lookup(request_id)

    @application.get("/documents/{document_id}/versions")
    async def versions(document_id: UUID) -> VersionList:
        return await runtime.require_service().versions(document_id)

    return application


app = create_app()

if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=8100, log_level="warning")
