from dataclasses import dataclass


@dataclass(frozen=True)
class Cancellation:
    requested: bool
    reason: str

    @classmethod
    def request(cls, reason: str) -> "Cancellation":
        if not reason:
            raise ValueError("reason required")
        return cls(True, reason)
