from datetime import timedelta
from typing import Protocol

from .retry_policy import RetryPolicy


class UnitRandom(Protocol):
    def unit(self) -> float: ...


def delays(policy: RetryPolicy, random: UnitRandom) -> tuple[timedelta, ...]:
    del random
    value = policy.initial_delay
    result: list[timedelta] = []
    for _ in range(policy.max_attempts - 1):
        result.append(value)
        value = min(policy.max_delay, value * policy.multiplier)
    return tuple(result)
