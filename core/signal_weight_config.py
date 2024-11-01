from dataclasses import dataclass, field
from typing import Dict

@dataclass
class SignalWeightConfig:
    source: str
    asset: str
    weight: float

@dataclass
class LeverageConfig:
    asset: str
    leverage: int

@dataclass
class ConfigData:
    signal_weights: Dict[str, Dict[str, float]] = field(default_factory=dict)  # source -> asset -> weight
    leverage_settings: Dict[str, int] = field(default_factory=dict)            # asset -> leverage
