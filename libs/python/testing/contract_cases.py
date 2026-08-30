from dataclasses import dataclass


@dataclass(frozen=True)
class ContractCase:
    name: str
    payload: bytes
    expected: bytes
