# Signal Processors

This directory contains signal processors that fetch and process trading signals from various sources.

## Setup

Before starting any processors, navigate to the project directory and activate the virtual environment:

```bash
cd $HOME/trading-engine
source .venv/bin/activate
```

## Configuration Changes

Different types of configuration changes require different service restarts:

1. **Processor Code Changes**:
   - Changes to processor class files (e.g., `bittensor_processor.py`) require a restart of the respective signal processor service
   - Does not require trade engine restart
   - Example: `pm2 restart bittensor-signals`

2. **Processor Enable/Disable**:
   - Enabling or disabling a processor in configuration requires a trade engine restart
   - Example: `pm2 restart trade-engine`

3. **Signal Weight Changes**:
   - Changes to `signal_weight_config.json` are picked up dynamically
   - No service restarts required
   - Takes effect in the next trade engine loop

## TradingView Processor

The TradingView processor (`tradingview_processor.py`) is not run directly by PM2. Instead, it is used by the TradingView endpoint (`tradingview_endpoint.py`) which receives webhooks from TradingView. For setup and configuration of the TradingView endpoint, see the [TradingView Endpoint Documentation](../signal_endpoints/README.md).

## Bittensor Signal Processor

The Bittensor signal processor fetches and processes signals from the Bittensor network. It:
- Fetches and ranks miners based on their performance
- Prepares signals at regular intervals (every 60 seconds)
- Stores signals to disk with atomic operations
- Automatically archives old signal files

### Starting the Processor

Start the Bittensor signal processor using PM2:

```bash
# Start the processor
pm2 start signal_processors/bittensor_processor.py --name bittensor-signals --interpreter python3

# Save the PM2 configuration
pm2 startup && pm2 save --force
```

### PM2 Log Management

Set up log rotation for the service:

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

### Monitoring

Monitor the processor using PM2 commands:

```bash
# View logs
pm2 logs bittensor-signals

# Monitor process
pm2 monit

# Restart processor
pm2 restart bittensor-signals

# Stop processor
pm2 stop bittensor-signals
```

### Signal Storage

Signals are stored in the `raw_signals/bittensor` directory:
- Current signals are stored as JSON files
- Files older than 3 days are automatically archived
- File operations are atomic to prevent partial reads
- Each signal contains depth, price, and timestamp information 