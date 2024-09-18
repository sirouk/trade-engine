from dataclasses import dataclass
from typing import Optional


@dataclass
class TradingViewSignal:
    symbol: str  # e.g., "BTCUSDT"
    direction: str  # e.g., "long", "short", "flat"
    action: str  # e.g., "buy", "sell"
    leverage: float  # e.g., 3.0
    size: str  # e.g., "0.015000000074999988/1"
    priority: str  # e.g., "high"
    takeprofit: float  # e.g., 0.0
    trailstop: float  # e.g., 0.0
    order_time: str  # e.g., "2024-08-01 01:00:20"
    order_price: float  # e.g., 64617.05
