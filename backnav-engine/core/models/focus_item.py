from dataclasses import dataclass
from typing import Optional


@dataclass
class FocusItem:
    app: str
    window_id: str
    title: str

    restore_type: Optional[str] = None
    restore_id: Optional[str] = None

    timestamp: int = 0
