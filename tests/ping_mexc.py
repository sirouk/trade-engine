from pymexc import spot, futures
from core.credentials import load_mexc_credentials

# Load MEXC Futures API credentials from the credentials file
credentials = load_mexc_credentials()

# Initialize MEXC Futures clients
futures_client = futures.HTTP(api_key=credentials.mexc.api_key, api_secret=credentials.mexc.api_secret)

# Test API connection with ping
try:
    response = futures_client.ping()
    print(f"Ping Response: {response}")
except Exception as e:
    print(f"Error: {str(e)}")


# Fetch account assets (requires authentication)
try:
    response = futures_client.assets()
    print(f"Assets: {response}")
except Exception as e:
    print(f"Error fetching assets: {str(e)}")