from core.credentials import Credentials, BittensorCredentials
import ujson
import os

CREDENTIALS_FILE = "signal_processors/credentials.json"

def load_credentials(file_path: str) -> Credentials:
    """Load credentials from a JSON file."""
    if not os.path.exists(file_path):
        # Return a default Credentials object when file is not found
        return Credentials(bittensor_sn8=BittensorCredentials(api_key=""))

    with open(file_path, 'r') as f:
        data = ujson.load(f)

    if bittensor_creds := data.get('bittensor'):
        return Credentials(bittensor_sn8=BittensorCredentials(**bittensor_creds))

    # Return default if no data found
    return Credentials(bittensor_sn8=BittensorCredentials(api_key=""))


def save_credentials(credentials: Credentials, file_path: str):
    """Save credentials to a JSON file."""
    data = {
        'bittensor': credentials.bittensor_sn8.__dict__ if credentials.bittensor_sn8 else None
    }
    with open(file_path, 'w') as f:
        ujson.dump(data, f, indent=4)


def ensure_bittensor_credentials(credentials: Credentials) -> Credentials:
    """Prompt for Bittensor credentials if they don't exist."""
    if not credentials.bittensor_sn8 or not credentials.bittensor_sn8.api_key:
        api_key = input("Enter your API key for Bittensor SN8: ")
        credentials.bittensor_sn8 = BittensorCredentials(api_key=api_key)
    return credentials


def prompt_for_credentials(file_path: str):
    """Ensure all necessary credentials are present by prompting the user."""
    credentials = load_credentials(file_path)
    
    # Prompt for Bittensor credentials
    credentials = ensure_bittensor_credentials(credentials)
    
    # Save the updated credentials
    save_credentials(credentials, file_path)
    
    print("Credentials have been updated and saved.")


if __name__ == '__main__':
    # Prompt for all credentials when running the script directly
    prompt_for_credentials(CREDENTIALS_FILE)
