from dataclasses import dataclass

@dataclass
class BittensorCredentials:
    api_key: str
    endpoint: str

@dataclass
class BybitCredentials:
    api_key: str
    api_secret: str

@dataclass
class BloFinCredentials:
    api_key: str
    api_secret: str

@dataclass
class Credentials:
    bittensor_sn8: BittensorCredentials
    bybit: BybitCredentials
    blofin: BloFinCredentials


import ujson
import os

CREDENTIALS_FILE = "credentials.json"

def load_credentials(file_path: str) -> Credentials:
    """Load credentials from a JSON file."""
    if not os.path.exists(file_path):
        # Return default Credentials objects when the file is not found
        return Credentials(
            bittensor_sn8=BittensorCredentials(api_key="", endpoint=""),
            bybit=BybitCredentials(api_key="", api_secret=""),
            blofin=BloFinCredentials(api_key="", api_secret="")
        )

    with open(file_path, 'r') as f:
        data = ujson.load(f)

    bybit_creds = data.get('bybit', {})
    bittensor_creds = data.get('bittensor_sn8', {})
    blofin_creds = data.get('blofin', {})

    return Credentials(
        bybit=BybitCredentials(
            api_key=bybit_creds.get('api_key', ""),
            api_secret=bybit_creds.get('api_secret', "")
        ),
        bittensor_sn8=BittensorCredentials(
            api_key=bittensor_creds.get('api_key', ""),
            endpoint=bittensor_creds.get('endpoint', "")
        ),
        blofin=BloFinCredentials(
            api_key=blofin_creds.get('api_key', ""),
            api_secret=blofin_creds.get('api_secret', "")
        )
    )

def save_credentials(credentials: Credentials, file_path: str):
    """Save credentials to a JSON file."""
    data = {
        'bybit': credentials.bybit.__dict__ if credentials.bybit else None,
        'bittensor_sn8': credentials.bittensor_sn8.__dict__ if credentials.bittensor_sn8 else None,
        'blofin': credentials.blofin.__dict__ if credentials.blofin else None
    }
    with open(file_path, 'w') as f:
        ujson.dump(data, f, indent=4)

def prompt_for_changes(credentials_name: str, skip_prompt: bool = False) -> bool:
    """Ask the user if they want to change the credentials."""
    while not skip_prompt:
        change = input(f"{credentials_name} credentials are already set. Do you want to change them? (yes/no): ").strip().lower()
        if change in ['yes', 'no']:
            return change == 'yes'
        print("Please enter 'yes' or 'no'.")
    return False

def ensure_bybit_credentials(credentials: Credentials, skip_prompt: bool = False) -> Credentials:
    """Prompt for Bybit API credentials if they don't exist, or ask to change them."""
    # Ask if the user wants to change existing credentials
    if credentials.bybit.api_key and credentials.bybit.api_secret and not prompt_for_changes("Bybit",skip_prompt):
        return credentials

    if not credentials.bybit.api_key or prompt_for_changes("Bybit API key", skip_prompt):
        api_key = input("Enter your Bybit API key: ")
        credentials.bybit.api_key = api_key

    if not credentials.bybit.api_secret or prompt_for_changes("Bybit API secret", skip_prompt):
        api_secret = input("Enter your Bybit API secret: ")
        credentials.bybit.api_secret = api_secret

    save_credentials(credentials, CREDENTIALS_FILE)
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

def ensure_blofin_credentials(credentials: Credentials, skip_prompt: bool = False) -> Credentials:
    """Prompt for BloFin API credentials if they don't exist, or ask to change them."""
    if credentials.blofin.api_key and credentials.blofin.api_secret and not prompt_for_changes("BloFin", skip_prompt):
        return credentials

    if not credentials.blofin.api_key or prompt_for_changes("BloFin API key", skip_prompt):
        api_key = input("Enter your BloFin API key: ")
        credentials.blofin.api_key = api_key

    if not credentials.blofin.api_secret or prompt_for_changes("BloFin API secret", skip_prompt):
        api_secret = input("Enter your BloFin API secret: ")
        credentials.blofin.api_secret = api_secret

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

def prompt_for_credentials(file_path: str):
    """Ensure all necessary credentials are present by prompting the user."""
    credentials = load_credentials(file_path)
    
    # Prompt for Bybit and Bittensor credentials or ask to change them
    credentials = ensure_bybit_credentials(credentials)
    credentials = ensure_bittensor_credentials(credentials)
    credentials = ensure_blofin_credentials(credentials)
    
    # Save the updated credentials
    save_credentials(credentials, file_path)
    
    print("Credentials have been updated and saved.")


if __name__ == '__main__':
    # Prompt for all credentials when running the script directly
    prompt_for_credentials(CREDENTIALS_FILE)
