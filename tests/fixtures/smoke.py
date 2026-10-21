import json
import sys

from pydantic import ValidationError

from agent.contracts import ContractContext, ContractViolation, EssayRequest, validate_contract
from tests.fixtures.cases import ACCEPTED_EDGE_FIXTURES, ContractCase, rejection_cases


def main() -> None:
    context = ContractCase.load("complete.json").parse()
    validate_contract(context)
    serialized = context.model_dump_json()
    restored = ContractContext.model_validate_json(serialized)
    validate_contract(restored)
    assert restored == context
    result = restored.result
    assert result is not None
    assert result.body == (
        "I sorted library books. Order can help shared work.\n\nMy task was sorting books."
    )
    assert result.character_count == 102
    for name in ACCEPTED_EDGE_FIXTURES:
        edge = ContractCase.load(name).parse()
        validate_contract(edge)
        assert ContractContext.model_validate_json(edge.model_dump_json()) == edge
    malformed_outcomes: list[dict[str, str]] = []
    for rejection in rejection_cases():
        try:
            changed = ContractCase.load("complete.json").replace(rejection.path, rejection.value)
            validate_contract(changed.parse())
        except ValidationError as error:
            malformed_outcomes.append(
                {
                    "scenario": rejection.name,
                    "observable": "rejected",
                    "error_type": type(error).__name__,
                    "detail": str(error),
                }
            )
        except ContractViolation as error:
            malformed_outcomes.append(
                {
                    "scenario": rejection.name,
                    "observable": "rejected",
                    "error_type": type(error).__name__,
                    "detail": str(error),
                }
            )
        else:
            raise AssertionError(rejection.name)
    sparse = EssayRequest.model_validate({})
    assert sparse.experiences == ()
    _ = sys.stdout.write(
        json.dumps(
            {
                "invocation": ".venv/bin/python -m tests.fixtures.smoke",
                "scope": (
                    "Public DTO parse/validate/serialize only; no model or product runtime claim"
                ),
                "fictional_sources": True,
                "accepted_edge_roundtrips": list(ACCEPTED_EDGE_FIXTURES),
                "sparse_request": {"observable": "accepted", "experience_count": 0},
                "roundtrip": {
                    "observable": "equal",
                    "version_id": result.version_id,
                    "evidence_version": result.evidence_version,
                    "body": result.body,
                    "copy_text": result.copy_text,
                    "character_count": result.character_count,
                    "generation_status": result.generation_status,
                    "missing_required_result": result.structure[2].coverage,
                },
                "malformed_and_stale": malformed_outcomes,
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n"
    )


if __name__ == "__main__":
    main()
