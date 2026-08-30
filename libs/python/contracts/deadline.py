from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Protocol


class Clock(Protocol):
    def now(self) -> datetime: ...


@dataclass(frozen=True)
class Deadline:
    expires_at: datetime

    def expired(self, clock: Clock) -> bool:
        return clock.now() >= self.expires_at

    def remaining(self, clock: Clock) -> timedelta:
        return max(self.expires_at - clock.now(), timedelta())
