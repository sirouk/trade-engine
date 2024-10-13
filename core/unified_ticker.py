from dataclasses import dataclass
from typing import Optional

@dataclass
class UnifiedTicker:
    symbol: str
    bid: float
    ask: float
    last: float
    volume: float
    exchange: Optional[str] = None  # Exchange (optional)
