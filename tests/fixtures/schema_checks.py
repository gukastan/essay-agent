from pydantic import BaseModel, JsonValue, TypeAdapter


def assert_strict_schema(model: type[BaseModel]) -> None:
    pending: list[JsonValue] = [TypeAdapter(JsonValue).validate_python(model.model_json_schema())]
    while pending:
        node = pending.pop()
        match node:
            case dict():
                properties = node.get("properties")
                if properties is not None:
                    assert isinstance(properties, dict)
                    required = node.get("required", [])
                    assert isinstance(required, list)
                    assert set(required) == set(properties)
                    assert node.get("additionalProperties") is False
                pending.extend(node.values())
            case list():
                pending.extend(node)
            case str() | int() | float() | None:
                continue
