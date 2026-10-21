from pathlib import Path
from uuid import uuid4

import pytest

from agent.api_models import ChatResponse
from agent.app_runtime import RuntimeFactories
from agent.contract_base import ContractViolation
from agent.contracts import EssayRequest, StoredParent, VersionId, validate_contract
from agent.fake_llm import FastLLM, QualityLLM
from agent.review_normalization import review_context, unavailable_review
from tests.api_support import client_for
from tests.review_graph_support import Cycles


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.mark.anyio
@pytest.mark.parametrize("repairs", [0, 1, 2])
async def test_persisted_parent_reaches_review_repair_and_delivery(
    tmp_path: Path, repairs: int
) -> None:
    script = Cycles(repairs=repairs)
    factories = RuntimeFactories(
        fast=lambda _: FastLLM(script), quality=lambda _: QualityLLM(script)
    )
    async with client_for(tmp_path / "parents.db", factories) as client:
        request = EssayRequest()
        initial = ChatResponse.model_validate_json(
            (await client.post("/chat", content=request.model_dump_json())).text
        ).result
        revision = request.model_copy(
            update={"request_id": uuid4(), "parent_version_id": initial.version_id}
        )
        reply = await client.post("/chat", content=revision.model_dump_json())
        assert reply.status_code == 200
        final = ChatResponse.model_validate_json(reply.text).result
        assert final.body
        payload = script.payloads[-1]
        assert payload.repair_count == repairs
        assert payload.stored_parent == StoredParent(
            document_id=initial.document_id, version_id=initial.version_id
        )
        assert "previous_draft" not in payload.model_dump()
        bundle, review = unavailable_review(payload, replace_body=False)
        for parent, code in (
            (None, "parent_missing"),
            (StoredParent(document_id=uuid4(), version_id=VersionId("wrong")), "parent_mismatch"),
        ):
            invalid = payload.model_copy(update={"stored_parent": parent})
            with pytest.raises(ContractViolation, match=code):
                validate_contract(review_context(invalid, bundle, review))
