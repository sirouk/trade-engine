from dataclasses import dataclass
import ujson as json
import os
try:
    import ccxt
    CCXT_AVAILABLE = True
except ImportError:
    CCXT_AVAILABLE = False
    print("Warning: CCXT not installed. Install with: pip install ccxt")

@dataclass
class BittensorCredentials:
    api_key: str
    endpoint: str

@dataclass
class BybitCredentials:
    api_key: str
    api_secret: str
    leverage_override: int = 0

@dataclass
class BloFinCredentials:
    api_key: str
    api_secret: str
    api_passphrase: str
    leverage_override: int = 0
    copy_trading: bool = False

@dataclass
class KuCoinCredentials:
    api_key: str
    api_secret: str
    api_passphrase: str
    leverage_override: int = 0
    
@dataclass
class MEXCCredentials:
    api_key: str
    api_secret: str
    leverage_override: int = 0

@dataclass
class BingXCredentials:
    api_key: str
    api_secret: str
    leverage_override: int = 0

@dataclass
class CCXTCredentials:
    """Generic CCXT credentials for any supported exchange"""
    exchange_name: str
    api_key: str
    api_secret: str
    api_passphrase: str = ""  # Optional, some exchanges need it
    leverage_override: int = 0
    enabled: bool = True
    copy_trading: bool = False  # Flag for copy trading accounts

@dataclass
class Credentials:
    bittensor_sn8: BittensorCredentials
    bybit: BybitCredentials
    blofin: BloFinCredentials
    kucoin: KuCoinCredentials
    mexc: MEXCCredentials
    bingx: BingXCredentials
    ccxt_list: list = None  # List of CCXTCredentials, renamed from ccxt to ccxt_list


CREDENTIALS_FILE = "credentials.json"

def validate_ccxt_exchange(exchange_name: str) -> bool:
    """Validate if an exchange is supported by CCXT."""
    if not CCXT_AVAILABLE:
        print("CCXT is not installed. Cannot validate exchange.")
        return False
    
    exchange_id = exchange_name.lower()
    return exchange_id in ccxt.exchanges

def list_popular_ccxt_exchanges():
    """List some popular CCXT exchanges."""
    popular = [
        'binance', 'okx', 'bybit', 'gate', 'huobi', 'kucoin',
        'kraken', 'bitget', 'bingx', 'mexc', 'bitfinex', 'bitstamp'
    ]
    return [ex for ex in popular if ex in ccxt.exchanges] if CCXT_AVAILABLE else []

def load_credentials(file_path: str) -> Credentials:
    """Load credentials from a JSON file."""
    if not os.path.exists(file_path):
        # Return default Credentials objects when the file is not found
        return Credentials(
            bittensor_sn8=BittensorCredentials(api_key="", endpoint=""),
            bybit=BybitCredentials(api_key="", api_secret="", leverage_override=0),
            blofin=BloFinCredentials(api_key="", api_secret="", api_passphrase="", leverage_override=0),
            kucoin=KuCoinCredentials(api_key="", api_secret="", api_passphrase="", leverage_override=0),
            mexc=MEXCCredentials(api_key="", api_secret="", leverage_override=0),
            bingx=BingXCredentials(api_key="", api_secret="", leverage_override=0),
            ccxt_list=None,
        )

    with open(file_path, 'r', encoding='utf-8') as f:
        data = json.load(f)

    bittensor_creds = data.get('bittensor_sn8', {})
    bybit_creds = data.get('bybit', {})
    blofin_creds = data.get('blofin', {})
    kucoin_creds = data.get('kucoin', {})
    mexc_creds = data.get('mexc', {})
    bingx_creds = data.get('bingx', {})
    ccxt_creds = data.get('ccxt', {})

    # Build ccxt_list from either new format or migrate from old format
    ccxt_list = None
    if ccxt_creds:
        if 'ccxt_list' in ccxt_creds:
            # New format with list
            ccxt_list = [
                CCXTCredentials(
                    exchange_name=cred.get('exchange_name', ""),
                    api_key=cred.get('api_key', ""),
                    api_secret=cred.get('api_secret', ""),
                    api_passphrase=cred.get('api_passphrase', ""),
                    leverage_override=int(cred.get('leverage_override', 0)),
                    enabled=cred.get('enabled', True),
                    copy_trading=cred.get('copy_trading', False)
                )
                for cred in ccxt_creds.get('ccxt_list', [])
            ]
        else:
            # Old format - migrate to list
            ccxt_list = [CCXTCredentials(
                exchange_name=ccxt_creds.get('exchange_name', ""),
                api_key=ccxt_creds.get('api_key', ""),
                api_secret=ccxt_creds.get('api_secret', ""),
                api_passphrase=ccxt_creds.get('api_passphrase', ""),
                leverage_override=int(ccxt_creds.get('leverage_override', 0)),
                enabled=ccxt_creds.get('enabled', True),
                copy_trading=ccxt_creds.get('copy_trading', False)
            )] if ccxt_creds.get('exchange_name') else None

    credentials = Credentials(
        bittensor_sn8=BittensorCredentials(
            api_key=bittensor_creds.get('api_key', ""),
            endpoint=bittensor_creds.get('endpoint', ""),
        ),
        bybit=BybitCredentials(
            api_key=bybit_creds.get('api_key', ""),
            api_secret=bybit_creds.get('api_secret', ""),
            leverage_override=int(bybit_creds.get('leverage_override', 0)),
        ),
        blofin=BloFinCredentials(
            api_key=blofin_creds.get('api_key', ""),
            api_secret=blofin_creds.get('api_secret', ""),
            api_passphrase=blofin_creds.get('api_passphrase', ""),
            leverage_override=int(blofin_creds.get('leverage_override', 0)),
            copy_trading=blofin_creds.get('copy_trading', False),
        ),
        kucoin=KuCoinCredentials(
            api_key=kucoin_creds.get('api_key', ""),
            api_secret=kucoin_creds.get('api_secret', ""),
            api_passphrase=kucoin_creds.get('api_passphrase', ""),
            leverage_override=int(kucoin_creds.get('leverage_override', 0)),
        ),
        mexc=MEXCCredentials(
            api_key=mexc_creds.get('api_key', ""),
            api_secret=mexc_creds.get('api_secret', ""),
            leverage_override=int(mexc_creds.get('leverage_override', 0)),
        ),
        bingx=BingXCredentials(
            api_key=bingx_creds.get('api_key', ""),
            api_secret=bingx_creds.get('api_secret', ""),
            leverage_override=int(bingx_creds.get('leverage_override', 0)),
        ),
        ccxt_list=ccxt_list,
    )

    return credentials

def save_credentials(credentials: Credentials, file_path: str):
    """Save credentials to a JSON file."""
    data = {
        'bittensor_sn8': credentials.bittensor_sn8.__dict__ if credentials.bittensor_sn8 else None,
        'bybit': credentials.bybit.__dict__ if credentials.bybit else None,
        'blofin': credentials.blofin.__dict__ if credentials.blofin else None,
        'kucoin': credentials.kucoin.__dict__ if credentials.kucoin else None,
        'mexc': credentials.mexc.__dict__ if credentials.mexc else None,
        'bingx': credentials.bingx.__dict__ if credentials.bingx else None,
        'ccxt': {
            'ccxt_list': [ccxt_cred.__dict__ for ccxt_cred in credentials.ccxt_list]
        } if credentials.ccxt_list else None,
    }
    with open(file_path, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=4)

def prompt_for_changes(credentials_name: str, skip_prompt: bool = False) -> bool:
    """Ask the user if they want to change the credentials."""
    while not skip_prompt:
        change = input(f"{credentials_name} credentials are already set. Do you want to change them? (yes/Enter to skip): ").strip().lower()
        if change == 'yes':
            return True
        elif change == '' or change == 'no':  # Empty input (Enter) or 'no' means skip
            return False
        print("Please enter 'yes' or press Enter to skip.")
    return False

def prompt_for_leverage_override(exchange_name, current_leverage=0):
    """Prompt the user to assign a leverage override for an exchange.
    A value > 0 will override the leverage passed in the reconcile function."""
    default_msg = f" (press Enter for current value: {current_leverage})" if current_leverage else " (press Enter to skip)"
    while True:
        try:
            override = input(f"Enter leverage override for {exchange_name}{default_msg}: ").strip()
            if not override:
                return current_leverage
            value = int(override)
            if value >= 0:
                return value
            print("Please enter a non-negative integer.")
        except ValueError:
            print("Please enter an integer value.")

def ensure_ccxt_credentials(credentials: Credentials, skip_prompt: bool = False) -> Credentials:
    """Prompt for CCXT exchange credentials."""
    if not CCXT_AVAILABLE:
        print("\nCCXT is not installed. Skipping CCXT exchange configuration.")
        print("To use CCXT exchanges, install with: pip install 'ccxt[async]'")
        return credentials
    
    # Ask if user wants to configure a CCXT exchange
    if not skip_prompt:
        # Check if we already have CCXT exchanges configured
        if credentials.ccxt_list:
            print(f"\nCurrently configured CCXT exchanges: {', '.join([c.exchange_name for c in credentials.ccxt_list])}")
            configure = input("\nDo you want to add a new exchange or edit an existing one? (yes/Enter to skip): ").strip().lower()
        else:
            configure = input("\nDo you want to configure a CCXT-compatible exchange? (yes/Enter to skip): ").strip().lower()
        
        if configure != 'yes':
            return credentials
    
    # If we have existing exchanges, show them with options
    if credentials.ccxt_list:
        print("\nExisting exchanges:")
        for i, cred in enumerate(credentials.ccxt_list):
            status = "enabled" if cred.enabled else "disabled"
            print(f"  {i+1}. {cred.exchange_name} ({status})")
        print(f"  {len(credentials.ccxt_list)+1}. Add a new exchange")
        
        while True:
            choice = input(f"\nSelect an option (1-{len(credentials.ccxt_list)+1}): ").strip()
            try:
                choice_num = int(choice)
                if 1 <= choice_num <= len(credentials.ccxt_list):
                    # Edit existing exchange
                    existing_index = choice_num - 1
                    exchange_name = credentials.ccxt_list[existing_index].exchange_name
                    print(f"\nEditing {exchange_name} configuration...")
                    break
                elif choice_num == len(credentials.ccxt_list) + 1:
                    # Add new exchange
                    existing_index = None
                    exchange_name = None
                    break
                else:
                    print("Invalid option. Please try again.")
            except ValueError:
                print("Please enter a number.")
    else:
        existing_index = None
        exchange_name = None
    
    # If adding new exchange, get the name
    if exchange_name is None:
        # Show available exchanges
        print("\nCCXT supports hundreds of exchanges for futures trading.")
        popular = list_popular_ccxt_exchanges()
        if popular:
            print(f"Popular exchanges: {', '.join(popular)}")
        print(f"Total supported: {len(ccxt.exchanges)} exchanges")
        
        # Get exchange name
        while True:
            exchange_name = input("\nEnter the exchange name (e.g., binance, okx, bingx): ").strip().lower()
            if not exchange_name:
                print("Exchange name cannot be empty.")
                continue
                
            if not validate_ccxt_exchange(exchange_name):
                print(f"'{exchange_name}' is not a valid CCXT exchange.")
                show_all = input("Show all supported exchanges? (yes/Enter to skip): ").strip().lower()
                if show_all == 'yes':
                    print("\nAll CCXT exchanges:")
                    for i, ex in enumerate(sorted(ccxt.exchanges)):
                        print(f"{ex:20}", end="")
                        if (i + 1) % 4 == 0:
                            print()
                    print()
                continue
                
            # Check if this exchange already exists
            for i, ccxt_cred in enumerate(credentials.ccxt_list or []):
                if ccxt_cred.exchange_name == exchange_name:
                    use_existing = input(f"\n{exchange_name} is already configured. Do you want to edit it? (yes/no): ").strip().lower()
                    if use_existing == 'yes':
                        existing_index = i
                        break
                    else:
                        print("Please choose a different exchange name.")
                        exchange_name = None
                        break
            
            if exchange_name:  # If we have a valid new exchange name
                break
    
    # If user chose not to edit existing, go back to start
    if exchange_name is None:
        return ensure_ccxt_credentials(credentials, skip_prompt=False)
    
    # Create new CCXT credential
    new_ccxt_cred = CCXTCredentials(
        exchange_name=exchange_name,
        api_key="",
        api_secret="",
        api_passphrase="",
        leverage_override=0,
        enabled=True,
        copy_trading=False
    )
    
    # Get API credentials
    api_key = input(f"Enter your {exchange_name} API key: ").strip()
    new_ccxt_cred.api_key = api_key
    
    api_secret = input(f"Enter your {exchange_name} API secret: ").strip()
    new_ccxt_cred.api_secret = api_secret
    
    # Always ask for passphrase - many exchanges use it
    # Users can press Enter to skip if not needed
    passphrase = input(f"Enter your {exchange_name} API passphrase (press Enter if not required): ").strip()
    new_ccxt_cred.api_passphrase = passphrase
    
    # Leverage override
    new_ccxt_cred.leverage_override = prompt_for_leverage_override(exchange_name, new_ccxt_cred.leverage_override)
    
    # Copy trading
    copy_trading = input(f"Is this a copy trading account? (yes/no) [no]: ").strip().lower()
    new_ccxt_cred.copy_trading = copy_trading == 'yes'
    
    # Enable/disable
    enable = input(f"Enable {exchange_name} for trading? (yes/Enter for yes): ").strip().lower()
    new_ccxt_cred.enabled = enable != 'no'
    
    # Add or update the credential
    if existing_index is not None:
        # Update existing
        credentials.ccxt_list[existing_index] = new_ccxt_cred
        print(f"\n{exchange_name} configuration updated!")
    else:
        # Add new
        if not credentials.ccxt_list:
            credentials.ccxt_list = []
        credentials.ccxt_list.append(new_ccxt_cred)
        print(f"\n{exchange_name} configured successfully!")
    
    save_credentials(credentials, CREDENTIALS_FILE)
    
    # Ask if they want to add/edit another CCXT exchange
    add_another = input("\nDo you want to add or edit another CCXT exchange? (yes/Enter to skip): ").strip().lower()
    if add_another == 'yes':
        return ensure_ccxt_credentials(credentials, skip_prompt=False)
    
    return credentials

def ensure_bittensor_credentials(credentials: Credentials, skip_prompt: bool = False) -> Credentials:
    """Prompt for Bittensor credentials if they don't exist, or ask to change them."""
    # Ask if the user wants to change existing credentials
    if credentials.bittensor_sn8.api_key and credentials.bittensor_sn8.endpoint and not prompt_for_changes("Bittensor SN8", skip_prompt):
        return credentials

    if not credentials.bittensor_sn8.api_key or prompt_for_changes("Bittensor SN8 API key", skip_prompt):
        api_key = input("Enter your API key for Bittensor SN8: ")
        credentials.bittensor_sn8.api_key = api_key
    
    if not credentials.bittensor_sn8.endpoint or prompt_for_changes("Bittensor SN8 API endpoint", skip_prompt):
        endpoint = input("Enter the Bittensor endpoint URL: ")
        credentials.bittensor_sn8.endpoint = endpoint

    save_credentials(credentials, CREDENTIALS_FILE)
    return credentials

def ensure_bybit_credentials(credentials: Credentials, skip_prompt: bool = False) -> Credentials:
    """Prompt for Bybit API credentials if they don't exist, or ask to change them, including a leverage override."""
    # Check if credentials exist and if we want to change them
    has_credentials = credentials.bybit.api_key and credentials.bybit.api_secret
    if has_credentials and not prompt_for_changes("Bybit", skip_prompt):
        # Still ask about leverage override even if other credentials aren't changing
        if prompt_for_changes("Bybit leverage override", skip_prompt):
            credentials.bybit.leverage_override = prompt_for_leverage_override("Bybit", credentials.bybit.leverage_override)
        return credentials

    if not credentials.bybit.api_key or prompt_for_changes("Bybit API key", skip_prompt):
        api_key = input("Enter your Bybit API key: ")
        credentials.bybit.api_key = api_key

    if not credentials.bybit.api_secret or prompt_for_changes("Bybit API secret", skip_prompt):
        api_secret = input("Enter your Bybit API secret: ")
        credentials.bybit.api_secret = api_secret

    # Always prompt for leverage override when setting up new credentials
    credentials.bybit.leverage_override = prompt_for_leverage_override("Bybit", credentials.bybit.leverage_override)
    save_credentials(credentials, CREDENTIALS_FILE)
    return credentials

def ensure_blofin_credentials(credentials: Credentials, skip_prompt: bool = False) -> Credentials:
    """Prompt for BloFin API credentials if they don't exist, or ask to change them, including a leverage override."""
    # Check if credentials exist and if we want to change them
    has_credentials = (credentials.blofin.api_key and 
                      credentials.blofin.api_secret and 
                      credentials.blofin.api_passphrase)
    if has_credentials and not prompt_for_changes("BloFin", skip_prompt):
        # Still ask about leverage override even if other credentials aren't changing
        if prompt_for_changes("BloFin leverage override", skip_prompt):
            credentials.blofin.leverage_override = prompt_for_leverage_override("BloFin", credentials.blofin.leverage_override)
        if prompt_for_changes("BloFin copy trading mode", skip_prompt):
            current_mode = "yes" if credentials.blofin.copy_trading else "no"
            copy_mode = input(
                f"Is this a BloFin copy trading account? (yes/no) [current: {current_mode}]: "
            ).strip().lower()
            if copy_mode in ("yes", "no"):
                credentials.blofin.copy_trading = copy_mode == "yes"
        return credentials

    if not credentials.blofin.api_key or prompt_for_changes("BloFin API key", skip_prompt):
        api_key = input("Enter your BloFin API key: ")
        credentials.blofin.api_key = api_key

    if not credentials.blofin.api_secret or prompt_for_changes("BloFin API secret", skip_prompt):
        api_secret = input("Enter your BloFin API secret: ")
        credentials.blofin.api_secret = api_secret

    if not credentials.blofin.api_passphrase or prompt_for_changes("BloFin API passphrase", skip_prompt):
        passphrase = input("Enter your BloFin API passphrase: ")
        credentials.blofin.api_passphrase = passphrase

    # Always prompt for leverage override when setting up new credentials
    credentials.blofin.leverage_override = prompt_for_leverage_override("BloFin", credentials.blofin.leverage_override)
    current_mode = "yes" if credentials.blofin.copy_trading else "no"
    copy_mode = input(
        f"Is this a BloFin copy trading account? (yes/no) [default: {current_mode}]: "
    ).strip().lower()
    if copy_mode in ("yes", "no"):
        credentials.blofin.copy_trading = copy_mode == "yes"
    save_credentials(credentials, CREDENTIALS_FILE)
    return credentials

def ensure_kucoin_credentials(credentials: Credentials, skip_prompt: bool = False) -> Credentials:
    """Prompt for KuCoin API credentials if they don't exist, or ask to change them, including a leverage override."""
    # Check if credentials exist and if we want to change them
    has_credentials = (credentials.kucoin.api_key and 
                      credentials.kucoin.api_secret and 
                      credentials.kucoin.api_passphrase)
    if has_credentials and not prompt_for_changes("KuCoin", skip_prompt):
        # Still ask about leverage override even if other credentials aren't changing
        if prompt_for_changes("KuCoin leverage override", skip_prompt):
            credentials.kucoin.leverage_override = prompt_for_leverage_override("KuCoin", credentials.kucoin.leverage_override)
        return credentials

    if not credentials.kucoin.api_key or prompt_for_changes("KuCoin API key", skip_prompt):
        api_key = input("Enter your KuCoin API key: ")
        credentials.kucoin.api_key = api_key

    if not credentials.kucoin.api_secret or prompt_for_changes("KuCoin API secret", skip_prompt):
        api_secret = input("Enter your KuCoin API secret: ")
        credentials.kucoin.api_secret = api_secret

    if not credentials.kucoin.api_passphrase or prompt_for_changes("KuCoin API passphrase", skip_prompt):
        passphrase = input("Enter your KuCoin API passphrase: ")
        credentials.kucoin.api_passphrase = passphrase

    # Always prompt for leverage override when setting up new credentials
    credentials.kucoin.leverage_override = prompt_for_leverage_override("KuCoin", credentials.kucoin.leverage_override)
    save_credentials(credentials, CREDENTIALS_FILE)
    return credentials

def ensure_mexc_credentials(credentials: Credentials, skip_prompt: bool = False) -> Credentials:
    """Prompt for MEXC API credentials if they don't exist, or ask to change them, including a leverage override."""
    # Check if credentials exist and if we want to change them
    has_credentials = credentials.mexc.api_key and credentials.mexc.api_secret
    if has_credentials and not prompt_for_changes("MEXC", skip_prompt):
        # Still ask about leverage override even if other credentials aren't changing
        if prompt_for_changes("MEXC leverage override", skip_prompt):
            credentials.mexc.leverage_override = prompt_for_leverage_override("MEXC", credentials.mexc.leverage_override)
        return credentials

    if not credentials.mexc.api_key or prompt_for_changes("MEXC API key", skip_prompt):
        api_key = input("Enter your MEXC API key: ")
        credentials.mexc.api_key = api_key

    if not credentials.mexc.api_secret or prompt_for_changes("MEXC API secret", skip_prompt):
        api_secret = input("Enter your MEXC API secret: ")
        credentials.mexc.api_secret = api_secret

    # Always prompt for leverage override when setting up new credentials
    credentials.mexc.leverage_override = prompt_for_leverage_override("MEXC", credentials.mexc.leverage_override)
    save_credentials(credentials, CREDENTIALS_FILE)
    return credentials

def ensure_bingx_credentials(credentials: Credentials, skip_prompt: bool = False) -> Credentials:
    """Prompt for BingX API credentials if they don't exist, or ask to change them, including a leverage override."""
    # Check if credentials exist and if we want to change them
    has_credentials = credentials.bingx.api_key and credentials.bingx.api_secret
    if has_credentials and not prompt_for_changes("BingX", skip_prompt):
        # Still ask about leverage override even if other credentials aren't changing
        if prompt_for_changes("BingX leverage override", skip_prompt):
            credentials.bingx.leverage_override = prompt_for_leverage_override("BingX", credentials.bingx.leverage_override)
        return credentials

    if not credentials.bingx.api_key or prompt_for_changes("BingX API key", skip_prompt):
        api_key = input("Enter your BingX API key: ")
        credentials.bingx.api_key = api_key

    if not credentials.bingx.api_secret or prompt_for_changes("BingX API secret", skip_prompt):
        api_secret = input("Enter your BingX API secret: ")
        credentials.bingx.api_secret = api_secret

    # Always prompt for leverage override when setting up new credentials
    credentials.bingx.leverage_override = prompt_for_leverage_override("BingX", credentials.bingx.leverage_override)
    save_credentials(credentials, CREDENTIALS_FILE)
    return credentials


def load_bittensor_credentials():
    """Ensure all credentials are present, and load them if necessary."""
    credentials = load_credentials(CREDENTIALS_FILE)
    assert ensure_bittensor_credentials(credentials, skip_prompt=True)
    
    return credentials

def load_bybit_credentials():
    """Ensure all credentials are present, and load them if necessary."""
    credentials = load_credentials(CREDENTIALS_FILE)
    assert ensure_bybit_credentials(credentials, skip_prompt=True)
    
    return credentials

def load_blofin_credentials():
    """Ensure all BloFin credentials are present, and load them if necessary."""
    credentials = load_credentials(CREDENTIALS_FILE)
    assert ensure_blofin_credentials(credentials, skip_prompt=True)
    return credentials

def load_kucoin_credentials():
    """Ensure all KuCoin credentials are present, and load them if necessary."""
    credentials = load_credentials(CREDENTIALS_FILE)
    assert ensure_kucoin_credentials(credentials, skip_prompt=True)
    return credentials

def load_mexc_credentials() -> Credentials:
    """Ensure all MEXC credentials are present, and load them if necessary."""
    credentials = load_credentials(CREDENTIALS_FILE)
    assert ensure_mexc_credentials(credentials, skip_prompt=True)
    return credentials

def load_bingx_credentials() -> Credentials:
    """Ensure all BingX credentials are present, and load them if necessary."""
    credentials = load_credentials(CREDENTIALS_FILE)
    assert ensure_bingx_credentials(credentials, skip_prompt=True)
    return credentials

def load_ccxt_credentials() -> Credentials:
    """Load CCXT credentials if configured."""
    credentials = load_credentials(CREDENTIALS_FILE)
    if not credentials.ccxt_list or len(credentials.ccxt_list) == 0:
        raise ValueError("No CCXT exchange configured. Run 'python config/credentials.py' to configure.")
    return credentials


def prompt_for_credentials(file_path: str):
    """Ensure all necessary credentials are present by prompting the user."""
    credentials = load_credentials(file_path)
    
    # Prompt for Bybit and Bittensor credentials or ask to change them
    credentials = ensure_bittensor_credentials(credentials)
    credentials = ensure_bybit_credentials(credentials)
    credentials = ensure_blofin_credentials(credentials)
    credentials = ensure_kucoin_credentials(credentials)
    credentials = ensure_mexc_credentials(credentials)
    credentials = ensure_bingx_credentials(credentials)
    
    # Ask about CCXT exchanges
    credentials = ensure_ccxt_credentials(credentials)
    
    # Save the updated credentials
    save_credentials(credentials, file_path)
    
    print("\nCredentials have been updated and saved.")


if __name__ == '__main__':
    # Prompt for all credentials when running the script directly
    prompt_for_credentials(CREDENTIALS_FILE)
