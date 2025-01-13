# tradingview-webhooks endpoint

This endpoint is used to receive webhooks from TradingView. It is used to receive alerts from TradingView and store signals in the raw_signals directory.

### Prerequisites

Ensure you have the following installed:

- Python 3.6+ and in a virtual environment pip install -r requirements.txt
- Certbot (`sudo apt install certbot`)
- NGINX (`sudo apt install nginx-full`)
- PM2 (`npm install -g pm2`)

pm2 installation:

```bash
if command -v pm2 &> /dev/null
then
    pm2 startup && pm2 save --force
else
    sudo apt install jq npm -y
    sudo npm install pm2 -g && pm2 update
    npm install pm2@latest -g && pm2 update && pm2 save --force && pm2 startup && pm2 save
fi
```

### Start the endpoint

Run this manually first to set up the endpoint with your webhook domain name (ex. tv-webhook.domain.com)

```bash
python3 signal_endpoints/tradingview_endpoint.py tv-webhook.domain.com
```

Then stop the endpoint and run it as a service:

```bash
pm2 start signal_endpoints/tradingview_endpoint.py --name tradingview-endpoint --interpreter python3
pm2 startup && pm2 save --force
```

### Test the endpoint

Test the endpoint by sendint a POST with curl and a JSON payload:

```bash
curl -X POST http://127.0.0.1:8000/ -H "Content-Type: application/json" -d '{
    "symbol": "ETHUSDT",
    "direction": "long",
    "action": "buy",
    "leverage": "3",
    "size": "5.8/100",
    "priority": "high",
    "takeprofit": "0.0",
    "trailstop": "0.0",
    "price": "3328.25"
}'
```

### pm2 logs management

```bash
# PM2 Logrotate Setup

# Install pm2-logrotate module
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

### Other examples of trades (long, long again, exit, short, short again, exit) in curl


Long:
```bash
# long
curl -X POST -H "Content-Type: application/json" -d '{"symbol": "ETHUSDT", "direction": "long", "action": "buy", "leverage": "3", "size": "5.8/100", "priority": "high", "takeprofit": "0.0", "trailstop": "0.0", "price": "3328.25"}' http://localhost:8000/

# long again
curl -X POST -H "Content-Type: application/json" -d '{"symbol": "ETHUSDT", "direction": "long", "action": "buy", "leverage": "3", "size": "7.5/100", "priority": "high", "takeprofit": "0.0", "trailstop": "0.0", "price": "3315.33"}' http://localhost:8000/

# exit
curl -X POST -H "Content-Type: application/json" -d '{"symbol": "ETHUSDT", "direction": "flat", "action": "sell", "leverage": "", "size": "Exit @ 3263.55", "priority": "high", "takeprofit": "0.00", "trailstop": "0.00", "price": "3263.55"}' http://localhost:8000/
```

Short:
```bash
# short
curl -X POST -H "Content-Type: application/json" -d '{"symbol": "ETHUSDT", "direction": "short", "action": "sell", "leverage": "3", "size": "5.8/100", "priority": "high", "takeprofit": "0.0", "trailstop": "0.0", "price": "3365.25"}' http://localhost:8000/

# short again
curl -X POST -H "Content-Type: application/json" -d '{"symbol": "ETHUSDT", "direction": "short", "action": "sell", "leverage": "3", "size": "7.5/100", "priority": "high", "takeprofit": "0.0", "trailstop": "0.0", "price": "3375.33"}' http://localhost:8000/

# exit
curl -X POST -H "Content-Type: application/json" -d '{"symbol": "ETHUSDT", "direction": "flat", "action": "buy", "leverage": "", "size": "Exit @ 3245.55", "priority": "high", "takeprofit": "0.00", "trailstop": "0.00", "price": "3245.55"}' http://localhost:8000/
```

