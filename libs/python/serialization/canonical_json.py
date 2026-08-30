import json

type JsonValue = bool | int | str | list[JsonValue] | dict[str, JsonValue] | None


def encode(value: JsonValue) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
