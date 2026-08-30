from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class Event:
    name: str
    occurred_at: datetime
    fields: Mapping[str, object]
