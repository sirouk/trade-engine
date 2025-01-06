import json
import asyncio
from dataclasses import dataclass, asdict
from signal_processors.tradingview_processor import SIGNAL_SOURCE as TRADINGVIEW_SIGNAL_SOURCE, CORE_ASSET_MAPPING as TRADINGVIEW_ASSET_MAPPING
from signal_processors.bittensor_processor import SIGNAL_SOURCE as BITTENSOR_SIGNAL_SOURCE, CORE_ASSET_MAPPING as BITTENSOR_ASSET_MAPPING
from collections import defaultdict

CONFIG_FILE = "signal_weight_config.json"
STARTING_WEIGHT = 1.0


@dataclass
class SignalSource:
    name: str
    core_asset_mapping: dict


@dataclass
class SignalWeight:
    leverage: int
    weight: float
    
    
@dataclass
class SignalWeightConfig:
    source: SignalSource()
    symbol: str
    original_symbol: str
    config: SignalWeight()


def load_signal_sources():
    """Fetch each signal source."""
    signal_sources = []
    
    tradingview_source = SignalSource(
        name=TRADINGVIEW_SIGNAL_SOURCE,
        core_asset_mapping=TRADINGVIEW_ASSET_MAPPING
    )
    signal_sources.append(tradingview_source)
    
    bittensor_source = SignalSource(
        name=BITTENSOR_SIGNAL_SOURCE,
        core_asset_mapping=BITTENSOR_ASSET_MAPPING
    )
    signal_sources.append(bittensor_source)    

    return signal_sources


def prompt_for_leverage(symbol):
    """Prompt the user to assign leverage for a symbol."""
    while True:
        try:
            leverage = input(f"Enter leverage for {symbol}: ").strip()
            leverage = int(leverage)
            return leverage
        except ValueError:
            print("Please enter an integer value for leverage.")


def prompt_for_weight(symbol, source, original_symbol, remaining_weight):
    """Prompt user to assign a weight for a given symbol and source."""
    while True:
        try:
            weight = input(
                f"Assign weight for {symbol} from {source} ({original_symbol}) "
                f"(remaining weight: {remaining_weight:.2f}, press Enter to skip): "
            ).strip()
            if weight == "":
                print(f"Skipped {original_symbol} from {source}.\n")
                return 0.0  # Skip allocation
            weight = float(weight)
            if 0 <= weight <= remaining_weight:
                return weight
            else:
                print(f"Weight must be between 0 and {remaining_weight:.2f}. Try again.")
        except ValueError:
            print("Please enter a numeric value.")


def configure_signals(signal_sources):
    """Run through each unique asset and prompt for weight and leverage configurations."""
    all_signals = defaultdict(list)
    all_symbols = set()

    # Aggregate all sources into normalized signals
    for source in signal_sources:
        print(f"\nProcessing signals from {source.name}")
        normalized_signals = source.get_normalized_signals()
        all_symbols.update(normalized_signals.keys())
        print(f"Found {len(normalized_signals)} unique signals from {source.name}")
        for symbol, signal_data in normalized_signals.items():
            print(f"Adding {symbol} from {source.name}")
            all_signals[symbol].append((source.name, signal_data))

    asset_configs = []
    remaining_weight = STARTING_WEIGHT
    for symbol in all_symbols:
        print(f"\nConfiguring {symbol}")
        leverage = prompt_for_leverage(symbol)
        weights = []

        # Prompt weights for each source associated with the symbol
        for source_name, signal_data in all_signals[symbol]:
            weight = prompt_for_weight(
                symbol, source_name, signal_data["original_symbol"], remaining_weight
            )
            
            if weight > 0:
                weights.append(SignalWeightConfig(
                    symbol=symbol, 
                    source=source_name,
                    original_symbol=signal_data["original_symbol"], 
                    weight=weight
                ))
                remaining_weight -= weight
                
            assert remaining_weight >= 0, "Remaining weight should not be negative."                
            
        asset_configs.append(AssetConfig(symbol=symbol, leverage=leverage, signals=weights))

    return asset_configs

def print_summary(asset_configs):
    """Print a summary of the configuration data."""

    # Calculate total weight used and prepare summary
    total_weight_used = sum(
        signal.weight for asset in asset_configs for signal in asset.signals
    )
    summary = "\nSummary of Allocated Weights:\n"
    for asset in asset_configs:
        summary += f"\nAsset: {asset.symbol}, Leverage: {asset.leverage}\n"
        for signal in asset.signals:
            summary += f"  Source: {signal.source}, Original Symbol: {signal.original_symbol}, Weight: {signal.weight}\n"
    
    print(f"\nTotal Weight Budget Used: {total_weight_used:.2f} out of 1.0\n{summary}")

def save_config(asset_configs):
    """Save the configuration data to a JSON file and print a summary."""
    config_data = [asdict(config) for config in asset_configs]
    
    # Print summary of configuration
    print_summary(asset_configs)
    
    # Save configuration to file
    with open(CONFIG_FILE, 'w') as f:
        json.dump(config_data, f, indent=4)
    print(f"\nConfiguration saved to {CONFIG_FILE}")
    

def main():
    signal_sources = load_signal_sources()
    asset_configs = configure_signals(signal_sources)
    save_config(asset_configs)

if __name__ == "__main__":
    main()
