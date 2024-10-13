from dataclasses import dataclass
from typing import Optional

@dataclass
class UnifiedPosition:
    symbol: str  # Trading pair (e.g., BTC-USDT)
    size: float  # Size of the open position
    average_entry_price: float  # Average price of the position
    direction: str  # Either 'long' or 'short'
    leverage: Optional[float] = None  # Leverage, if applicable
    unrealized_pnl: Optional[float] = None  # Unrealized PnL (optional)
    exchange: Optional[str] = None  # Exchange (optional)

    def is_profitable(self, current_price: float) -> bool:
        if self.direction == "long":
            return current_price > self.average_entry_price
        elif self.direction == "short":
            return current_price < self.average_entry_price
        return False

    def calculate_position_value(self, current_price: float) -> float:
        return self.size * current_price

    def adjust_for_leverage(self) -> float:
        return self.size * self.leverage if self.leverage else self.size
