from core.credentials import Credentials, BittensorCredentials
import ujson
import os

CREDENTIALS_FILE = "signal_processors/credentials.json"

def load_credentials(file_path: str) -> Credentials:
    """Load credentials from a JSON file and ensure both api_key and endpoint are set."""
    if not os.path.exists(file_path):
        # Return a default Credentials object when the file is not found
        return Credentials(bittensor_sn8=BittensorCredentials(api_key="", endpoint=""))

    with open(file_path, 'r') as f:
        data = ujson.load(f)

    bittensor_creds = data.get('bittensor', {})
    
    # Ensure that both 'api_key' and 'endpoint' exist, defaulting to empty strings if missing
    api_key = bittensor_creds.get('api_key', "")
    endpoint = bittensor_creds.get('endpoint', "")

    return Credentials(bittensor_sn8=BittensorCredentials(api_key=api_key, endpoint=endpoint))


def save_credentials(credentials: Credentials, file_path: str):
    """Save credentials to a JSON file."""
    data = {
        'bittensor': credentials.bittensor_sn8.__dict__ if credentials.bittensor_sn8 else None
    }
    with open(file_path, 'w') as f:
        ujson.dump(data, f, indent=4)


def prompt_for_changes() -> bool:
    """Ask the user if they want to change the credentials."""
    while True:
        change = input("Credentials are already set. Do you want to change them? (yes/no): ").strip().lower()
        if change in ['yes', 'no']:
            return change == 'yes'
        print("Please enter 'yes' or 'no'.")


def ensure_bittensor_credentials(credentials: Credentials) -> Credentials:
    """Prompt for Bittensor credentials if they don't exist, or ask to change them."""
    # Ask if the user wants to change existing credentials
    if credentials.bittensor_sn8.api_key and credentials.bittensor_sn8.endpoint and not prompt_for_changes():
        return credentials

    if not credentials.bittensor_sn8.api_key or prompt_for_changes():
        api_key = input("Enter your API key for Bittensor SN8: ")
        credentials.bittensor_sn8.api_key = api_key
    
    if not credentials.bittensor_sn8.endpoint or prompt_for_changes():
        endpoint = input("Enter the Bittensor endpoint URL: ")
        credentials.bittensor_sn8.endpoint = endpoint
    
    return credentials


def prompt_for_credentials(file_path: str):
    """Ensure all necessary credentials are present by prompting the user."""
    credentials = load_credentials(file_path)
    
    # Prompt for Bittensor credentials or ask to change them
    credentials = ensure_bittensor_credentials(credentials)
    
    # Save the updated credentials
    save_credentials(credentials, file_path)
    
    print("Credentials have been updated and saved.")


if __name__ == '__main__':
    # Prompt for all credentials when running the script directly
    prompt_for_credentials(CREDENTIALS_FILE)
