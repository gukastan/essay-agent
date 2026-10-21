import pytest
from pydantic import ValidationError

from agent.contracts import Budget, ContractContext, Outline
from tests.fixtures.cases import ContractCase
from tests.fixtures.schema_checks import assert_strict_schema


def test_general_outline_can_have_no_personal_core_answer() -> None:
    case = ContractCase.load("complete.json").replace(("outline", "core_answer"), None)
    case = case.replace(("outline", "core_answer_fact_ids"), [])
    case = case.replace(("outline", "general_direction"), "Describe a general approach.")
    case = case.replace(("outline", "budget", "subtitle_reserved_chars"), None)
    outline = case.parse().outline
    assert outline is not None
    assert outline.core_answer is None
    assert outline.core_answer_fact_ids == ()
    assert outline.general_direction == "Describe a general approach."


def test_unknown_limit_preserves_null_subtitle_reservation() -> None:
    budget = Budget.model_validate(
        {
            "max_chars": None,
            "subtitle_reserved_chars": None,
            "separator_chars": 4,
            "usable_body_chars": None,
            "constraint_notes": [],
        }
    )
    assert budget.subtitle_reserved_chars is None
    assert budget.usable_body_chars is None


@pytest.mark.parametrize("reservation", [0, 20])
def test_unknown_limit_rejects_invented_subtitle_reservation(reservation: int) -> None:
    with pytest.raises(ValidationError, match="unknown_budget"):
        _ = Budget.model_validate(
            {
                "max_chars": None,
                "subtitle_reserved_chars": reservation,
                "separator_chars": 0,
                "usable_body_chars": None,
                "constraint_notes": [],
            }
        )


@pytest.mark.parametrize("reservation", [0, 20])
def test_known_limit_retains_numeric_subtitle_reservation(reservation: int) -> None:
    budget = Budget.model_validate(
        {
            "max_chars": 600,
            "subtitle_reserved_chars": reservation,
            "separator_chars": 4,
            "usable_body_chars": 596 - reservation,
            "constraint_notes": [],
        }
    )
    assert budget.subtitle_reserved_chars == reservation


def test_known_limit_requires_numeric_subtitle_reservation() -> None:
    with pytest.raises(ValidationError, match="known_budget"):
        _ = Budget.model_validate(
            {
                "max_chars": 600,
                "subtitle_reserved_chars": None,
                "separator_chars": 4,
                "usable_body_chars": 596,
                "constraint_notes": [],
            }
        )


def test_nullable_planning_fields_remain_required() -> None:
    with pytest.raises(ValidationError, match="subtitle_reserved_chars"):
        _ = Budget.model_validate(
            {
                "max_chars": None,
                "separator_chars": 0,
                "usable_body_chars": None,
                "constraint_notes": [],
            }
        )
    case = ContractCase.load("complete.json").replace(
        ("outline", "budget", "subtitle_reserved_chars"),
        None,
    )
    context = ContractContext.model_validate(case.data)
    assert context.outline is not None
    payload = context.outline.model_dump()
    del payload["core_answer"]
    with pytest.raises(ValidationError, match="core_answer"):
        _ = Outline.model_validate(payload)
    assert_strict_schema(Outline)
    assert_strict_schema(Budget)
