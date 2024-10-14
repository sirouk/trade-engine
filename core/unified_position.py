from dataclasses import dataclass

@dataclass
class UnifiedPosition:
    symbol: str  # Trading pair (e.g., BTC-USDT)
    size: float  # Size of the open position
    average_entry_price: float  # Average price of the position
    direction: str  # Either 'long' or 'short'
    leverage: float  # Leverage, if applicable
    unrealized_pnl: float # Unrealized PnL (optional)
    margin_mode: str  # ISOLATED_MARGIN or CROSS_MARGIN
    exchange: str # Exchange (optional)            
            
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
