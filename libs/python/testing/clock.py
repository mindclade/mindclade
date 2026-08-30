from datetime import UTC, datetime

from libs.python.time.clock import ManualClock


def fixed_clock() -> ManualClock:
    return ManualClock(datetime(2026, 8, 30, 12, tzinfo=UTC))
