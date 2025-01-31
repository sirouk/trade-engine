# Trade Engine

This is a trade engine that uses signals from various sources to execute trades on various exchanges. This is to be used for testing and development purposes. Use at your own risk.

### Installation

The trade engine requires Python 3.11+ and some system dependencies:

```bash
# Install python 3.11
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
cd $HOME
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
cd $HOME/trade-engine
deactivate;
rm -rf .venv
```

## Adding Credentials

Before running the trade engine, you'll need to configure your exchange API credentials. These are stored securely in `credentials.json`.

To set up the credentials, run the following command, which will prompt you to enter your API key(s):

```bash
cd $HOME/trade-engine
source .venv/bin/activate
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

## Configuring Asset Mappings

The trade engine needs to know how to map asset symbols from different signal sources to a unified format. Run the asset mapping configuration script:

```bash
cd $HOME/trade-engine
source .venv/bin/activate
python3 config/asset_mapping.py
```

For each signal source (tradingview and bittensor), you'll be shown current mappings and prompted to:

1. Enter the source asset symbol (e.g., ETHUSD for Bittensor or ETHUSDT for TradingView):
   ```
   Configuring mappings for bittensor
   Enter source asset symbol (e.g., ETHUSD) or press Enter to finish:
   ```

2. Enter the translated (unified) symbol. If a mapping already exists, you can press Enter to keep the current value:
   ```
   Enter translated asset symbol for ETHUSD (press Enter for current value: ETHUSDT):
   ```

3. Repeat for each asset you want to map, or press Enter without input to move to the next signal source.

The configuration will be saved to `asset_mapping_config.json`. Example configuration file:

```json
{
    "tradingview": {
        "BTCUSDT": "BTCUSDT",
        "ETHUSDT": "ETHUSDT"
    },
    "bittensor": {
        "BTCUSD": "BTCUSDT",
        "ETHUSD": "ETHUSDT"
    }
}
```

After configuration, a summary will be displayed showing all configured mappings for each signal source.

## Configuring Signal Weights

The trade engine uses weights to determine how much influence each signal source has for each trading pair. Run the configuration script:

```bash
cd $HOME/trade-engine
source .venv/bin/activate
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

The configuration will be saved to `signal_weight_config.json`. After configuration, a summary will be displayed showing all allocated weights and leverage values.

### Configuration Changes and Service Restarts

Different types of configuration changes require different service restarts:

1. **Signal Weight Changes** (`signal_weight_config.json`):
   - Changes are picked up dynamically by the trade engine
   - No restart required
   - Takes effect in the next trade engine loop

2. **Signal Processor Configuration**:
   - Changes to processor class files (e.g., `bittensor_processor.py`):
     - Requires restart of the respective signal processor service
     - Run: `pm2 restart bittensor-signals` for Bittensor changes
   - Enabling/disabling processors in configuration:
     - Requires trade engine restart
     - Run: `pm2 restart trade-engine`

Example configuration file:

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

First, start the signal processors. See the respective documentation for detailed setup:
- [TradingView Endpoint](signal_endpoints/README.md)
- [Signal Processors](signal_processors/README.md)

Then, run the trade engine manually to verify everything is working:

```bash
cd $HOME/trade-engine
source .venv/bin/activate
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

Set up log rotation for all services:

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
pm2 logs                           # View all logs
pm2 logs tradingview-endpoint      # View TradingView endpoint logs
pm2 logs bittensor-signals         # View Bittensor signal processor logs
pm2 logs trade-engine              # View trade engine logs

# Monitor processes
pm2 monit

# Restart services
pm2 restart all                    # Restart all services
pm2 restart tradingview-endpoint   # Restart TradingView endpoint
pm2 restart bittensor-signals      # Restart Bittensor signal processor
pm2 restart trade-engine           # Restart trade engine

# Stop services
pm2 stop all                       # Stop all services
pm2 stop tradingview-endpoint      # Stop TradingView endpoint
pm2 stop bittensor-signals         # Stop Bittensor signal processor
pm2 stop trade-engine              # Stop trade engine
```