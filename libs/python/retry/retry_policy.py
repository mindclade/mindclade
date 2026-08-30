from dataclasses import dataclass
from datetime import timedelta


@dataclass(frozen=True)
class RetryPolicy:
    max_attempts: int
    initial_delay: timedelta
    max_delay: timedelta
    multiplier: float = 2.0
    jitter_fraction: float = 0.0
