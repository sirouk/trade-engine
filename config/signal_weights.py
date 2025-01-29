import ujson as json
from dataclasses import dataclass, asdict
from signal_processors.tradingview_processor import TradingViewProcessor
from signal_processors.bittensor_processor import BittensorProcessor

CONFIG_FILE = "signal_weight_config.json"
STARTING_WEIGHT = 1.0

@dataclass
class SignalSource:
    name: str
    core_asset_mapping: dict

@dataclass
class SourceWeight:
    source: str
    weight: float

@dataclass
class UnifiedSymbolConfig:
    symbol: str
    leverage: int
    sources: list[SourceWeight]

def load_signal_sources():
    """Fetch each signal source."""
    tv = TradingViewProcessor()
    bt = BittensorProcessor()
    return [
        SignalSource(name=tv.SIGNAL_SOURCE, core_asset_mapping=tv.CORE_ASSET_MAPPING),
        SignalSource(name=bt.SIGNAL_SOURCE, core_asset_mapping=bt.CORE_ASSET_MAPPING),
    ]

def load_existing_config():
    """Load existing configuration if available."""
    try:
        with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
            config_data = json.load(f)
            configs = []
            for config in config_data:
                # Convert the sources list of dicts to list of SourceWeight objects
                sources = [SourceWeight(**source) for source in config['sources']]
                config['sources'] = sources
                configs.append(UnifiedSymbolConfig(**config))
            return configs
    except (FileNotFoundError, json.JSONDecodeError):
        return []

def get_existing_config(symbol, existing_configs):
    """Get existing configuration for a symbol if it exists."""
    for config in existing_configs:
        if config.symbol == symbol:
            return config
    return None

def prompt_for_leverage(symbol, existing_leverage=None):
    """Prompt the user to assign leverage for a symbol."""
    default_msg = f" (press Enter for current value: {existing_leverage})" if existing_leverage else ""
    while True:
        try:
            leverage = input(f"Enter leverage for {symbol}{default_msg}: ").strip()
            if not leverage and existing_leverage is not None:
                return existing_leverage
            return int(leverage)
        except ValueError:
            print("Please enter an integer value for leverage.")

def prompt_for_weight(symbol, source_name, remaining_weight, existing_weight=None):
    """Prompt user to assign a weight for a given source."""
    default_msg = f" (press Enter for current value: {existing_weight})" if existing_weight is not None else " (press Enter to skip)"
    while True:
        try:
            weight = input(
                f"Assign weight for {symbol} from {source_name} "
                f"(remaining weight: {remaining_weight:.2f}{default_msg}): "
            ).strip()
            if not weight:
                return existing_weight if existing_weight is not None else 0.0
            weight = float(weight)
            if 0 <= weight <= remaining_weight:
                return weight
            print(f"Weight must be between 0 and {remaining_weight:.2f}. Try again.")
        except ValueError:
            print("Please enter a numeric value.")

def configure_signals(signal_sources):
    """Configure weights and leverage for unified symbols."""
    unified_symbols = {}
    existing_configs = load_existing_config()

    # Build unified symbol mappings
    for source in signal_sources:
        for _, unified_symbol in source.core_asset_mapping.items():
            if unified_symbol not in unified_symbols:
                unified_symbols[unified_symbol] = []
            unified_symbols[unified_symbol].append(source.name)

    asset_configs = []

    for unified_symbol, sources in unified_symbols.items():
        print(f"\nConfiguring {unified_symbol}")
        existing_config = get_existing_config(unified_symbol, existing_configs)
        
        # Get existing leverage if available
        existing_leverage = existing_config.leverage if existing_config else None
        leverage = prompt_for_leverage(unified_symbol, existing_leverage)
        
        remaining_weight = STARTING_WEIGHT
        source_weights = []

        for source_name in sources:
            # Get existing weight if available
            existing_weight = None
            if existing_config:
                for source_weight in existing_config.sources:
                    if source_weight.source == source_name:
                        existing_weight = source_weight.weight
                        break
            
            weight = prompt_for_weight(unified_symbol, source_name, remaining_weight, existing_weight)
            if weight > 0:
                source_weights.append(SourceWeight(source=source_name, weight=weight))
                remaining_weight -= weight

            assert remaining_weight >= 0, "Remaining weight should not be negative."

        asset_configs.append(UnifiedSymbolConfig(
            symbol=unified_symbol, leverage=leverage, sources=source_weights
        ))

    return asset_configs

def print_summary(asset_configs):
    """Print a summary of the configuration data."""
    total_weight_used = sum(
        weight.weight for config in asset_configs for weight in config.sources
    )
    summary = "\nSummary of Allocated Weights:\n"
    for config in asset_configs:
        summary += (
            f"\nUnified Symbol: {config.symbol}, Leverage: {config.leverage}\n"
        )
        for source_weight in config.sources:
            summary += (
                f"  Source: {source_weight.source}, Weight: {source_weight.weight}\n"
            )
    print(f"\nTotal Weight Budget Used: {total_weight_used:.2f} out of {STARTING_WEIGHT}\n{summary}")

def save_config(asset_configs):
    """Save the configuration data to a JSON file and print a summary."""
    config_data = [asdict(config) for config in asset_configs]

    print_summary(asset_configs)

    with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
        json.dump(config_data, f, indent=4)
    print(f"\nConfiguration saved to {CONFIG_FILE}")

def main():
    signal_sources = load_signal_sources()
    asset_configs = configure_signals(signal_sources)
    save_config(asset_configs)

if __name__ == "__main__":
    main()
