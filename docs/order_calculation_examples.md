# Order Calculation Examples - CCXT Processor

## Overview

The CCXT processor automatically handles order size calculations, ensuring that:
1. Orders meet minimum size requirements
2. Orders are rounded to the correct precision
3. Large orders are automatically split into chunks
4. All calculations respect exchange specifications

## Key Results from Testing

### 🪙 Bitcoin (BTC/USDT:USDT)
- **Minimum Order**: 0.001 BTC (~$65 at $65,000/BTC)
- **Precision**: 0.001 BTC (3 decimal places)
- **Max Single Order**: 1,000 BTC (~$65M)

**Examples:**
| Desired USD | Actual BTC Order | Final USD Value |
|-------------|------------------|-----------------|
| $10         | 0.001 BTC       | $65.00         |
| $100        | 0.002 BTC       | $130.00        |
| $1,000      | 0.015 BTC       | $975.00        |
| $10,000     | 0.154 BTC       | $10,010.00     |

*Note: Small orders are rounded UP to meet minimum requirements*

### 💎 Ethereum (ETH/USDT:USDT)
- **Minimum Order**: 0.01 ETH (~$35 at $3,500/ETH)
- **Precision**: 0.01 ETH (2 decimal places)
- **Max Single Order**: 10,000 ETH (~$35M)

**Examples:**
| Desired USD | Actual ETH Order | Final USD Value |
|-------------|------------------|-----------------|
| $10         | 0.01 ETH        | $35.00         |
| $100        | 0.03 ETH        | $105.00        |
| $1,000      | 0.29 ETH        | $1,015.00      |
| $10,000     | 2.86 ETH        | $10,010.00     |

### 🌊 Ripple (XRP/USDT:USDT)
- **Minimum Order**: 1 XRP (~$0.60 at $0.60/XRP)
- **Precision**: 1 XRP (whole numbers only)
- **Max Single Order**: 1,000,000 XRP (~$600K)

**Examples:**
| Desired USD | Actual XRP Order | Final USD Value |
|-------------|------------------|-----------------|
| $10         | 17 XRP          | $10.20         |
| $100        | 167 XRP         | $100.20        |
| $1,000      | 1,667 XRP       | $1,000.20      |
| $10,000     | 16,667 XRP      | $10,000.20     |

## Important Notes

### ✅ Automatic Handling
- **Minimum Orders**: Orders below minimum are automatically increased
- **Precision**: All orders are rounded to exchange-required precision
- **Large Orders**: Orders exceeding max size are automatically split

### 📊 Leverage Examples
With a $10,000 position:
- 1x leverage = $10,000 margin required
- 5x leverage = $2,000 margin required
- 10x leverage = $1,000 margin required
- 20x leverage = $500 margin required
- 50x leverage = $200 margin required

### 🔧 Technical Details
- Contract Value: 1:1 for all linear USDT perpetuals
- Orders are placed as market orders by default
- Position sizes can be positive (long) or negative (short)
- The system uses CCXT's standardized format: `BASE/QUOTE:SETTLE`

## Summary

The order calculation system ensures that:
1. **All orders are valid** - Meet exchange requirements
2. **Precision is maintained** - Proper rounding for each asset
3. **Large orders work** - Automatic chunking when needed
4. **Small orders are handled** - Automatic adjustment to minimums

This means you can specify any reasonable USD amount, and the system will calculate the correct order size for each cryptocurrency automatically. 