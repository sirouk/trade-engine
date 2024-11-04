from dataclasses import dataclass, field
from typing import List, Optional, Dict


@dataclass
class BTTSN8TradePair:
    symbol: str
    original_symbol: str
    pair: str
    spread: float
    volume: float
    decimal_places: int


@dataclass
class BTTSN8Order:
    leverage: float
    order_type: str  # "LONG", "SHORT", "LIMIT", "MARKET", etc.
    order_uuid: str
    price: float
    price_sources: List[str]
    processed_ms: int
    rank: int
    trade_pair: BTTSN8TradePair


@dataclass
class BTTSN8Position:
    depth: float
    average_entry_price: float
    close_ms: Optional[int]  # None if position is open
    current_return: float
    is_closed_position: bool
    miner_hotkey: str
    net_leverage: float
    open_ms: int
    orders: List[BTTSN8Order]
    position_type: str  # "FLAT", "LONG", "SHORT", etc.
    position_uuid: str
    return_at_close: Optional[float]  # None if open
    trade_pair: BTTSN8TradePair


@dataclass
class BTTSN8MinerSignal:
    all_time_returns: float
    n_positions: int
    percentage_profitable: float
    positions: List[BTTSN8Position]
    thirty_day_returns: Optional[float]  # Optional for time-based signals
