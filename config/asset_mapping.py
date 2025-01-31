import ujson as json
from dataclasses import dataclass
from signal_processors.tradingview_processor import TradingViewProcessor
from signal_processors.bittensor_processor import BittensorProcessor

CONFIG_FILE = "asset_mapping_config.json"

@dataclass
class SignalSource:
    name: str
    core_asset_mapping: dict

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
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}

def prompt_for_mapping(source_name, existing_mappings=None):
    """Prompt user to input source and translated asset symbols."""
    mappings = {}
    existing_mappings = existing_mappings or {}
    source_mappings = existing_mappings.get(source_name, {})
    
    while True:
        print(f"\nConfiguring mappings for {source_name}")
        print("Enter source asset symbol (e.g., ETHUSD) or press Enter to finish:")
        source_symbol = input().strip()
        
        if not source_symbol:
            break
            
        # Check if mapping exists and show as default
        existing_translated = source_mappings.get(source_symbol)
        default_msg = f" (press Enter for current value: {existing_translated})" if existing_translated else ""
        
        print(f"Enter translated asset symbol for {source_symbol}{default_msg}:")
        translated_symbol = input().strip()
        
        # Use existing value if user just pressed Enter
        if not translated_symbol and existing_translated:
            translated_symbol = existing_translated
        
        if translated_symbol:
            mappings[source_symbol] = translated_symbol
            
    # Merge with existing mappings to preserve unmapped assets
    return {**source_mappings, **mappings}

def print_summary(config):
    """Print a summary of the asset mappings configuration."""
    print("\nAsset Mappings Summary:")
    for source, mappings in config.items():
        print(f"\nSignal Source: {source}")
        for source_symbol, translated_symbol in mappings.items():
            print(f"  {source_symbol} -> {translated_symbol}")

def save_config(config):
    """Save the configuration data to a JSON file and print a summary."""
    print_summary(config)
    
    with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
        json.dump(config, f, indent=4)
    print(f"\nConfiguration saved to {CONFIG_FILE}")

def main():
    signal_sources = load_signal_sources()
    existing_config = load_existing_config()
    
    # Initialize new config with existing mappings
    config = existing_config.copy()
    
    # Configure mappings for each signal source
    for source in signal_sources:
        print(f"\nCurrent mappings for {source.name}:")
        if source.name in config:
            for src, trans in config[source.name].items():
                print(f"  {src} -> {trans}")
        
        mappings = prompt_for_mapping(source.name, existing_config)
        if mappings:
            config[source.name] = mappings
    
    save_config(config)

if __name__ == "__main__":
    main() 