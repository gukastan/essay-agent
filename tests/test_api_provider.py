from pathlib import Path
from uuid import uuid4

import pytest

from agent.api_models import ChatResponse
from agent.app_runtime import RuntimeFactories
from agent.contracts import EssayRequest
from tests.api_support import client_for
from tests.llm_support import Reply, provider


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.mark.anyio
async def test_real_sdk_transport_failure_still_delivers_and_revises(tmp_path: Path) -> None:
    error_prefix = '{"error":{"message":"private provider detail",'
    denied = Reply(
        error_prefix + '"type":"authentication_error","code":"invalid_api_key"}}',
        status=401,
    )
    async with provider((denied,) * 8) as fast, provider((denied,) * 12, "quality") as quality:
        factories = RuntimeFactories(fast=lambda _: fast.adapter, quality=lambda _: quality.adapter)
        async with client_for(tmp_path / "provider.db", factories) as client:
            request = EssayRequest()
            first = await client.post("/chat", content=request.model_dump_json())
            assert first.status_code == 200
            result = ChatResponse.model_validate_json(first.text).result
            revision = request.model_copy(
                update={"request_id": uuid4(), "parent_version_id": result.version_id}
            )
            second = await client.post("/chat", content=revision.model_dump_json())
            assert second.status_code == 200
            final = ChatResponse.model_validate_json(second.text).result
            assert final.body
            assert "private provider detail" not in second.text
            assert len(fast.requests) == 4
            assert len(quality.requests) == 6
            assert all(
                item.response_format.type == "json_schema"
                for item in (*fast.requests, *quality.requests)
            )
