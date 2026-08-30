from typing import Protocol


class SerializableMessage(Protocol):
    def SerializeToString(  # noqa: N802
        self, *, deterministic: bool = False
    ) -> bytes: ...


def encode_deterministic(message: SerializableMessage) -> bytes:
    return message.SerializeToString(deterministic=True)
