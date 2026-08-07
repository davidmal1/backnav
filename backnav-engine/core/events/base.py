from dataclasses import dataclass, field
from time import time


@dataclass(slots=True, kw_only=True)
class Event:
    timestamp: float = field(default_factory=time)
