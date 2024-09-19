from dataclasses import dataclass, field
from typing import List, Optional

@dataclass
class BybitBalance:
    asset: str
    available_balance: float
    wallet_balance: float
    unrealized_pnl: float

@dataclass
class BybitPosition:
    symbol: str
    side: str  # "Buy" or "Sell"
    entry_price: float
    leverage: float
    size: float
    unrealized_pnl: float

@dataclass
class BybitOrder:
    order_id: str
    symbol: str
    side: str  # "Buy" or "Sell"
    order_type: str  # "Limit", "Market", etc.
    price: float
    qty: float
    time_in_force: str  # "GTC", "IOC", etc.
    status: str  # "New", "Filled", etc.

@dataclass
class BybitAccountState:
    balances: List[BybitBalance] = field(default_factory=list)
    open_positions: List[BybitPosition] = field(default_factory=list)
    open_orders: List[BybitOrder] = field(default_factory=list)
