from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path
from typing import ClassVar, Final

from pydantic import BaseModel, ConfigDict, JsonValue, TypeAdapter

from agent.contracts import ContractContext

FIXTURES: Final = Path(__file__).parent
PAYLOAD: Final = TypeAdapter(dict[str, JsonValue])
PATH_ERROR: Final = "Fixture path does not match JSON structure"
ACCEPTED_EDGE_FIXTURES: Final = (
    "repairable.json",
    "unparsed.json",
    "fallback.json",
    "suggestions.json",
    "removed-fallback.json",
    "merged-sections.json",
)


class Rejection(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True)
    name: str
    path: tuple[str | int, ...]
    value: JsonValue


def rejection_cases() -> tuple[Rejection, ...]:
    return TypeAdapter(tuple[Rejection, ...]).validate_json(
        (FIXTURES / "rejections.json").read_text(),
    )


def child_value(node: JsonValue, key: str | int) -> JsonValue:
    match node, key:
        case dict(), str():
            return node[key]
        case list(), int():
            return node[key]
        case _:
            raise AssertionError(PATH_ERROR)


@dataclass(frozen=True, slots=True)
class ContractCase:
    data: dict[str, JsonValue]

    @classmethod
    def load(cls, name: str) -> "ContractCase":
        return cls(PAYLOAD.validate_json((FIXTURES / name).read_text()))

    def replace(self, path: tuple[str | int, ...], value: JsonValue) -> "ContractCase":
        data = deepcopy(self.data)
        cursor: JsonValue = data
        for key in path[:-1]:
            cursor = child_value(cursor, key)
        match cursor, path[-1]:
            case dict(), str() as key:
                cursor[key] = value
            case list(), int() as key:
                cursor[key] = value
            case _:
                raise AssertionError(PATH_ERROR)
        return ContractCase(data)

    def parse(self) -> ContractContext:
        return ContractContext.model_validate(self.data)
