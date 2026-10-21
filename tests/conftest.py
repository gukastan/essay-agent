import pytest

from tests.fixtures.cases import ContractCase


@pytest.fixture
def source_case() -> ContractCase:
    return ContractCase.load("sources.json")


@pytest.fixture
def complete_case() -> ContractCase:
    return ContractCase.load("complete.json")
