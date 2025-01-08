# tradingview-webhooks endpoint

This endpoint is used to receive webhooks from TradingView. It is used to receive alerts from TradingView and store signals in the raw_signals directory.

### Start the endpoint

Run this manually first to set up the endpoint with your webhook domain name (ex. tv-webhook.domain.com)

```bash
python3 signal_endpoints/tradingview_endpoint.py tv-webhook.domain.com
```

Then stop the endpoint and run it as a service:

```bash
pm2 start signal_endpoints/tradingview_endpoint.py --name tradingview_endpoint --interpreter python3
```

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
    "trailstop": "0.0"
}'
```
