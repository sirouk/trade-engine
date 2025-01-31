import ujson as json
from dataclasses import dataclass
from collections import OrderedDict
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
            config = json.load(f)
            # Convert each source's mappings to OrderedDict to maintain order
            return {source: OrderedDict(mappings) for source, mappings in config.items()}
    except (FileNotFoundError, json.JSONDecodeError):
        return {}

def get_user_choice(prompt: str, valid_choices: list) -> str:
    """Get a valid choice from the user."""
    while True:
        choice = input(prompt).strip().lower()
        if choice in valid_choices:
            return choice
        print(f"Please enter one of: {', '.join(valid_choices)}")

def modify_existing_mappings(source_mappings: OrderedDict) -> OrderedDict:
    """Review and modify existing mappings one by one."""
    modified_mappings = OrderedDict()
    
    print("\nReviewing existing mappings:")
    print("For each mapping, choose:")
    print("  k - keep the mapping as is")
    print("  m - modify the mapping")
    print("  r - remove the mapping")
    
    for source_symbol, translated_symbol in source_mappings.items():
        print(f"\nCurrent mapping: {source_symbol} -> {translated_symbol}")
        choice = get_user_choice("Keep/Modify/Remove (k/m/r)? ", ['k', 'm', 'r'])
        
        if choice == 'k':
            modified_mappings[source_symbol] = translated_symbol
        elif choice == 'm':
            print(f"Enter new translated symbol for {source_symbol}")
            print(f"(current value: {translated_symbol}):")
            new_symbol = input().strip()
            if new_symbol:
                modified_mappings[source_symbol] = new_symbol
            else:
                modified_mappings[source_symbol] = translated_symbol
    
    return modified_mappings

def prompt_for_mapping(source_name, existing_mappings=None):
    """Prompt user to input source and translated asset symbols."""
    mappings = OrderedDict()
    existing_mappings = existing_mappings or {}
    source_mappings = existing_mappings.get(source_name, OrderedDict())
    
    # First, ask what to do with existing mappings
    if source_mappings:
        print(f"\nCurrent mappings for {source_name}:")
        for src, trans in source_mappings.items():
            print(f"  {src} -> {trans}")
        
        print("\nWhat would you like to do with existing mappings?")
        print("  k - keep all existing mappings")
        print("  m - modify existing mappings one by one")
        print("  n - start fresh with no mappings")
        
        choice = get_user_choice("Choose (k/m/n): ", ['k', 'm', 'n'])
        
        if choice == 'k':
            mappings.update(source_mappings)
        elif choice == 'm':
            mappings.update(modify_existing_mappings(source_mappings))
    
    while True:
        print(f"\nConfiguring mappings for {source_name}")
        print("Enter source asset symbol (e.g., ETHUSD) or press Enter to finish:")
        source_symbol = input().strip()
        
        if not source_symbol:
            break
            
        # Check if symbol already exists
        if source_symbol in mappings:
            print(f"Warning: {source_symbol} is already mapped to {mappings[source_symbol]}")
            update = get_user_choice("Would you like to update this mapping? (y/n): ", ['y', 'n'])
            
            if update == 'n':
                continue
        
        # Check if mapping exists in current session
        existing_translated = mappings.get(source_symbol)
        default_msg = f" (press Enter for current value: {existing_translated})" if existing_translated else ""
        
        print(f"Enter translated asset symbol for {source_symbol}{default_msg}:")
        translated_symbol = input().strip()
        
        # Use existing value if user just pressed Enter
        if not translated_symbol and existing_translated:
            translated_symbol = existing_translated
        
        if translated_symbol:
            # Remove any existing mapping to this translated symbol to prevent duplicates
            for key in list(mappings.keys()):
                if mappings[key] == translated_symbol and key != source_symbol:
                    print(f"Warning: Removing existing mapping {key} -> {translated_symbol}")
                    del mappings[key]
            
            mappings[source_symbol] = translated_symbol
    
    return mappings

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
    
    # Convert OrderedDict to regular dict for JSON serialization while maintaining order
    config_to_save = {source: dict(mappings) for source, mappings in config.items()}
    
    with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
        json.dump(config_to_save, f, indent=4)
    print(f"\nConfiguration saved to {CONFIG_FILE}")

def main():
    signal_sources = load_signal_sources()
    existing_config = load_existing_config()
    
    # Initialize new config
    config = OrderedDict()
    
    # Configure mappings for each signal source
    for source in signal_sources:
        mappings = prompt_for_mapping(source.name, existing_config)
        if mappings:
            config[source.name] = mappings
    
    save_config(config)

if __name__ == "__main__":
    main() 