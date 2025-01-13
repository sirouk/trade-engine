# Trade Engine

This is a trade engine that uses signals from various sources to execute trades on various exchanges. This is to be used for testing and development purposes. Use at your own risk.

### Installation

The trade engine requires Python 3.11+ and some system dependencies:

```bash
sudo add-apt-repository ppa:deadsnakes/ppa
sudo apt update
sudo apt install -y python3.11 python3.11-venv

# Install PM2 if not already installed
if command -v pm2 &> /dev/null
then
    pm2 startup && pm2 save --force
else
    sudo apt install jq npm -y
    sudo npm install pm2 -g && pm2 update
    npm install pm2@latest -g && pm2 update && pm2 save --force && pm2 startup && pm2 save
fi
```

Then clone the repository:

```bash
cd ~/
git clone https://github.com/sirouk/trade-engine
cd ./trade-engine
```

Make a python virtual environment and install the dependencies:

```bash
python3.11 -m venv .venv
source .venv/bin/activate
pip install -e .
```

You should now have all required dependencies from the `pyproject.toml`.

If you need to cleanup and reinstall packages:

```bash
cd ~/trading-engine
deactivate;
rm -rf .venv
```

## Adding Credentials

Before running the trade engine, you'll need to configure your exchange API credentials. These are stored securely in `credentials.json`.

To set up the credentials, run the following command, which will prompt you to enter your API key(s):

```bash
python3 config/credentials.py
```

You'll be prompted for the following credentials:

- Bittensor SN8:
  ```
  Enter your API key for Bittensor SN8: <your-api-key>
  Enter the Bittensor endpoint URL: <endpoint-url>
  ```

- Bybit:
  ```
  Enter your Bybit API key: <your-api-key>
  Enter your Bybit API secret: <your-api-secret>
  ```

- BloFin:
  ```
  Enter your BloFin API key: <your-api-key>
  Enter your BloFin API secret: <your-api-secret>
  Enter your BloFin API passphrase: <your-passphrase>
  ```

- KuCoin:
  ```
  Enter your KuCoin API key: <your-api-key>
  Enter your KuCoin API secret: <your-api-secret>
  Enter your KuCoin API passphrase: <your-passphrase>
  ```

- MEXC:
  ```
  Enter your MEXC API key: <your-api-key>
  Enter your MEXC API secret: <your-api-secret>
  ```

## Configuring Signal Weights

The trade engine uses weights to determine how much influence each signal source has for each trading pair. Run the configuration script:

```bash
python3 config/signal_weights.py
```

You'll be prompted to configure each trading pair:

1. Set the leverage (1-20) for each symbol. If previously configured, the current value will be shown as default:
   ```
   Configuring BTCUSDT
   Enter leverage for BTCUSDT (press Enter for current value: 3): 
   ```

2. Assign weights to each signal source (weights must sum to ≤ 1.0). Previously configured weights will be shown as defaults:
   ```
   Assign weight for BTCUSDT from tradingview (remaining weight: 1.00, press Enter for current value: 0.10): 
   Assign weight for BTCUSDT from bittensor (remaining weight: 0.90, press Enter for current value: 0.15): 
   ```

The configuration will be saved to `signal_weight_config.json`. After configuration, a summary will be displayed showing all allocated weights and leverage values. Here's an example configuration file:

```json
[
    {
        "symbol": "BTCUSDT",
        "leverage": 3,
        "sources": [
            {
                "source": "tradingview",
                "weight": 0.1
            },
            {
                "source": "bittensor",
                "weight": 0.15
            }
        ]
    },
    {
        "symbol": "ETHUSDT",
        "leverage": 3,
        "sources": [
            {
                "source": "tradingview",
                "weight": 0.1
            },
            {
                "source": "bittensor",
                "weight": 0.15
            }
        ]
    }
]
```

- A weight of 0.0 or skipping a source disables it for that symbol
- Weights represent the influence of each signal source
- Total weights per symbol should not exceed 1.0
- Higher leverage increases position sizes proportionally
- Previously configured values can be kept by pressing Enter
- A summary of all configurations will be displayed after setup

To update either configuration later, simply rerun the respective configuration script.



## Running the Trade Engine

First, run the trade engine manually to verify everything is working:

```bash
python3 execute_trades.py
```

### Setting up PM2 Service

Once verified, set up the trade engine as a PM2 service:

```bash
# Start the trade engine with PM2
pm2 start execute_trades.py --name trade-engine --interpreter python3

# Ensure PM2 starts on system boot
pm2 startup && pm2 save --force
```

### PM2 Log Management

Set up log rotation for the trade engine:

```bash
# Install pm2-logrotate module if not already installed
pm2 install pm2-logrotate

# Set maximum size of logs to 50M before rotation
pm2 set pm2-logrotate:max_size 50M

# Retain 10 rotated log files
pm2 set pm2-logrotate:retain 10

# Enable compression of rotated logs
pm2 set pm2-logrotate:compress true

# Set rotation interval to every 6 hours
pm2 set pm2-logrotate:rotateInterval '00 */6 * * *'
```

### Useful PM2 Commands

```bash
# View logs
pm2 logs trade-engine

# Monitor processes
pm2 monit

# Restart the trade engine
pm2 restart trade-engine

# Stop the trade engine
pm2 stop trade-engine
```
