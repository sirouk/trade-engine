# Generic CCXT Processor Documentation

## Overview

The Generic CCXT Processor allows you to use **any CCXT-supported exchange** with the trading engine. This modular approach means you can easily switch between or add new exchanges without writing custom code.

## Features

- **Universal Compatibility**: Works with 100+ CCXT-supported exchanges
- **Dynamic Configuration**: Add new exchanges through the credentials system
- **Standardized Interface**: Same API as native processors (ByBit, KuCoin, etc.)
- **Automatic Validation**: Verifies exchange names against CCXT's supported list
- **Full Feature Support**: All standard trading operations (positions, orders, balances)

## Setup

### 1. Install CCXT

```bash
pip install "ccxt[async]"
```

Or if using the project's pyproject.toml:

```bash
pip install -e .
```

### 2. Configure an Exchange

Run the credentials setup:

```bash
python config/credentials.py
```

When prompted, choose to configure a CCXT-compatible exchange:

```
Do you want to configure a CCXT-compatible exchange? (yes/no): yes

CCXT supports hundreds of exchanges for futures trading.
Popular exchanges: binance, okx, bybit, gate, huobi, kucoin, kraken, bitget, bingx, mexc, bitfinex
Total supported: 100+ exchanges

Enter the exchange name (e.g., binance, okx, bingx): bingx
Enter your bingx API key: YOUR_API_KEY
Enter your bingx API secret: YOUR_SECRET
Enter leverage override for bingx (press Enter to skip): 
Enable bingx for trading? (yes/no) [yes]: yes

bingx configured successfully!
```

### 3. Supported Exchanges

The system supports any CCXT exchange that offers perpetual futures. Popular options include:

- **Binance**: The largest crypto exchange
- **OKX**: Advanced trading features
- **Bybit**: Popular derivatives platform
- **Gate.io**: Wide variety of pairs
- **Huobi**: Established exchange
- **KuCoin**: User-friendly platform
- **Kraken**: US-compliant exchange
- **Bitget**: Copy trading features
- **BingX**: Social trading
- **MEXC**: Many altcoins
- **Bitfinex**: Professional trading
- **Bitstamp**: One of the oldest

To see all supported exchanges, run:

```python
from account_processors.ccxt_processor import CCXTProcessor
exchanges = CCXTProcessor.list_supported_exchanges()
print(f"Total: {len(exchanges)} exchanges")
print(exchanges)
```

## Usage

### Basic Example

```python
import asyncio
from account_processors.ccxt_processor import CCXTProcessor

async def main():
    # Create processor - uses exchange from credentials
    async with CCXTProcessor() as processor:
        print(f"Using exchange: {processor.exchange_name}")
        
        # Fetch balance
        balance = await processor.fetch_balance("USDT")
        print(f"USDT Balance: {balance}")
        
        # Fetch ticker
        ticker = await processor.fetch_tickers("BTC/USDT:USDT")
        print(f"BTC Ticker: {ticker}")
        
        # Open a position
        order = await processor.open_market_position(
            symbol="BTC/USDT:USDT",
            side="buy",
            size=0.001,
            leverage=5,
            margin_mode="isolated"
        )
        
        # Check positions
        positions = await processor.fetch_and_map_positions("BTC/USDT:USDT")
        for pos in positions:
            print(f"Position: {pos}")

if __name__ == "__main__":
    asyncio.run(main())
```

### Switching Exchanges

To switch between exchanges, simply run the credentials setup again:

```bash
python config/credentials.py
```

The system will detect your existing CCXT configuration and ask if you want to change it.

### Multiple Exchange Support

While the current implementation supports one CCXT exchange at a time, you can:

1. Use native processors (ByBit, KuCoin, etc.) alongside CCXT
2. Switch between CCXT exchanges by updating credentials
3. Extend the system to support multiple CCXT instances

## Symbol Format

CCXT uses a standardized symbol format for perpetual futures:
- Format: `BASE/QUOTE:SETTLE`
- Example: `BTC/USDT:USDT` for BTC perpetual settled in USDT

The processor automatically converts from signal format:
- `BTCUSDT` → `BTC/USDT:USDT`
- `ETHUSDT` → `ETH/USDT:USDT`

## Exchange-Specific Considerations

### API Keys

Different exchanges have different API key requirements:

- **Basic** (most exchanges): API Key + Secret
- **Passphrase Required**: KuCoin, OKX, Bitget require an API passphrase
- **IP Whitelisting**: Some exchanges require IP address whitelisting

### Rate Limits

CCXT automatically handles rate limiting, but be aware:
- Each exchange has different limits
- The processor uses `enableRateLimit: True` by default
- You can adjust timeout settings if needed

### Margin Modes

Most exchanges support:
- **Isolated Margin**: Risk limited to position
- **Cross Margin**: Shared margin across positions

Some exchanges may require closing positions to change margin mode.

### Leverage

- Each exchange has different maximum leverage limits
- The processor supports leverage override in credentials
- Some exchanges require specific position modes for high leverage

## Testing

### Test Your Configuration

```bash
python tests/test_ccxt_processor.py
```

This will:
1. List all supported exchanges
2. Validate your configured exchange
3. Test basic connectivity
4. Show available markets

### Test Order Calculations

```bash
python tests/test_order_calculations_mock.py
```

This shows how orders are calculated without placing real trades.

## Troubleshooting

### "Exchange not supported" Error

- Ensure the exchange name is spelled correctly (lowercase)
- Check if the exchange supports perpetual futures
- Run the test script to see all valid exchange names

### API Authentication Errors

- Verify API keys are correct
- Check if API has trading permissions enabled
- Ensure IP whitelist includes your server (if required)
- For passphrase exchanges, ensure passphrase is correct

### Symbol Not Found

- Use CCXT's standard format: `BTC/USDT:USDT`
- Check if the exchange offers the specific perpetual contract
- Some exchanges use different naming (e.g., inverse contracts)

### Connection Issues

- Check if the exchange API is accessible from your location
- Some exchanges may be geo-restricted
- Verify firewall/proxy settings

## Advanced Usage

### Custom Exchange Parameters

You can modify exchange-specific parameters by editing the processor initialization:

```python
# In ccxt_processor.py __init__ method
self.exchange = exchange_class({
    'apiKey': self.credentials.ccxt.api_key,
    'secret': self.credentials.ccxt.api_secret,
    'enableRateLimit': True,
    'options': {
        'defaultType': 'swap',
        'defaultMarginMode': 'isolated',
        # Add exchange-specific options here
        'adjustForTimeDifference': True,  # For time sync issues
        'recvWindow': 10000,  # For timeout issues
    }
})
```

### Exchange-Specific Features

Some exchanges offer unique features accessible through CCXT:

```python
# Example: Accessing exchange-specific methods
if processor.exchange_name.lower() == 'binance':
    # Binance-specific feature
    result = await processor.exchange.fapiPrivateGetAccount()
```

## Benefits Over Native Processors

1. **Instant Exchange Support**: Add any CCXT exchange without coding
2. **Standardized API**: CCXT handles exchange differences
3. **Automatic Updates**: Exchange API changes handled by CCXT updates
4. **Extensive Documentation**: CCXT is well-documented
5. **Community Support**: Large CCXT community for help

## Migration from Native Processors

If you're currently using BingX through the native processor:

1. Configure BingX through CCXT credentials
2. Update your code to use `CCXTProcessor` instead of `BingX`
3. The interface remains the same - no other code changes needed

## Conclusion

The Generic CCXT Processor provides maximum flexibility for multi-exchange trading. With support for 100+ exchanges and a standardized interface, you can easily expand your trading operations across different platforms without writing custom integration code. 