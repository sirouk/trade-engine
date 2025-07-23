# Multi-CCXT Exchange Support

This document explains how to configure and use multiple CCXT exchanges in the trading system.

## Changes Made

### 1. Credential Prompts
- All credential prompts now accept Enter (empty input) to skip editing
- Previously required typing "no", now just press Enter to skip

### 2. Multiple CCXT Exchange Support
- Changed from single `ccxt` credential to `ccxt_list` array
- Each CCXT exchange is stored with unique exchange name
- Automatically migrates old single CCXT config to new list format

### 3. Automatic Multi-Exchange Trading
- `execute_trades.py` automatically loads all configured CCXT exchanges
- Creates separate processor instances for each exchange
- All CCXT exchanges are treated as separate accounts

## Configuration

### Adding CCXT Exchanges

Run the credential configuration:
```bash
python config/credentials.py
```

When prompted:
- Press Enter to skip existing credentials
- Type "yes" to add/modify CCXT exchanges
- You can add multiple exchanges (e.g., binance, okx, gate, etc.)
- Each exchange must have a unique name

### Example Configuration Flow

```
Currently configured CCXT exchanges: bybit
Do you want to add or modify a CCXT exchange? (yes/Enter to skip): yes

Enter the exchange name (e.g., binance, okx, bingx): binance
Enter your binance API key: YOUR_API_KEY
Enter your binance API secret: YOUR_API_SECRET
Enter leverage override for binance (press Enter to skip): 5
Enable binance for trading? (yes/Enter for yes): [Enter]

binance configured successfully!

Do you want to add another CCXT exchange? (yes/Enter to skip): yes

Enter the exchange name (e.g., binance, okx, bingx): okx
Enter your okx API key: YOUR_API_KEY
Enter your okx API secret: YOUR_API_SECRET
Enter your okx API passphrase: YOUR_PASSPHRASE
Enter leverage override for okx (press Enter to skip): 3
Enable okx for trading? (yes/Enter for yes): [Enter]

okx configured successfully!

Do you want to add another CCXT exchange? (yes/Enter to skip): [Enter]
```

## Credential Storage

The credentials are stored in `credentials.json` with this structure:

```json
{
    "ccxt": {
        "ccxt_list": [
            {
                "exchange_name": "bybit",
                "api_key": "...",
                "api_secret": "...",
                "api_passphrase": "",
                "leverage_override": 0,
                "enabled": true
            },
            {
                "exchange_name": "binance",
                "api_key": "...",
                "api_secret": "...",
                "api_passphrase": "",
                "leverage_override": 5,
                "enabled": true
            }
        ]
    }
}
```

## Testing

Test your multi-CCXT configuration:

```bash
python tests/test_multi_ccxt.py
```

This will:
- List all configured CCXT exchanges
- Test each exchange individually
- Test simultaneous operation of all exchanges

## How It Works

1. **Credential Loading**: When `execute_trades.py` starts, it loads all CCXT credentials
2. **Processor Creation**: For each enabled CCXT exchange, a separate `CCXTProcessor` instance is created
3. **Account List**: All CCXT processors are added to the main accounts list alongside native processors
4. **Trading**: Each CCXT exchange is treated as a separate account and receives trading signals

## Benefits

- **Multiple Exchange Support**: Trade on unlimited CCXT-supported exchanges
- **Unified Interface**: All CCXT exchanges use the same processor code
- **Easy Configuration**: Simple credential management for multiple exchanges
- **Parallel Trading**: All exchanges operate independently and concurrently

## Supported Exchanges

CCXT supports 100+ exchanges. Popular ones include:
- binance, okx, bybit, gate, huobi, kucoin
- kraken, bitget, bingx, mexc, bitfinex, bitstamp

Run this to see all supported exchanges:
```python
import ccxt
print(ccxt.exchanges)
```

## Exchange-Specific Features

### Copy Trading Accounts

Some exchanges (like BloFin) support both regular futures accounts and copy trading accounts. When configuring a CCXT exchange, you'll be asked:

```
Is this a copy trading account? (yes/no) [no]:
```

If you answer "yes", the CCXT processor will configure the exchange to use copy trading accounts by setting:

```python
config['options']['accountType'] = 'copy_trading'
```

This ensures that the exchange accesses your copy trading account balance and positions instead of the regular futures account.

#### Example: BloFin
- Regular futures account: Shows futures balance
- Copy trading account: Shows copy trading balance

The copy_trading flag is stored per exchange in your credentials, so you can have:
- Some exchanges using regular accounts
- Some exchanges using copy trading accounts
- Both types configured for the same exchange (as separate entries)

## Known Limitations

### BloFin Copy Trading via CCXT

**Important**: CCXT's BloFin implementation does not fully support copy trading accounts. While the native BloFin processor (`blofin_processor.py`) correctly uses copy trading specific endpoints (`get_positions_ct`, `place_order_ct`, etc.), CCXT uses standard endpoints that don't return copy trading positions.

**Recommendation**: For BloFin copy trading accounts, use the native BloFin processor instead of CCXT:
- Native processor: Full support for copy trading accounts
- CCXT processor: Limited/no support for copy trading positions

### Other CCXT Limitations

- Some exchange-specific features may not be available through CCXT's unified API
- Margin mode detection may be incorrect for some exchanges
- For production use with specific exchanges, consider using native processors when available for more accurate data

## Troubleshooting

1. **Exchange Not Found**: Make sure the exchange name matches CCXT's naming (lowercase)
2. **API Errors**: Verify API keys have futures trading permissions
3. **Passphrase Required**: Some exchanges (okx, kucoin, bitget) require API passphrase
4. **Rate Limits**: Each exchange has separate rate limiting built-in

## Migration from Old Format

The system automatically migrates from the old single CCXT format to the new list format.
Your existing CCXT configuration will be preserved as the first item in the list. 