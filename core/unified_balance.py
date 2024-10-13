from dataclasses import dataclass
from typing import Optional

@dataclass
class UnifiedBalance:
    instrument: str
    balance: float
    exchange: Optional[str] = None  # Exchange (optional)