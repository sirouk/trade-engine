#!/usr/bin/env python3
"""
Test script for the generic CCXT processor
"""

import asyncio
import sys
import os

# Add parent directory to path to import modules
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from account_processors.ccxt_processor import CCXTProcessor


async def test_ccxt_processor():
    """Test the generic CCXT processor"""
    print("Testing Generic CCXT Processor")
    print("=" * 50)
    
    # First, show all supported exchanges
    print("\nChecking CCXT supported exchanges...")
    try:
        exchanges = CCXTProcessor.list_supported_exchanges()
        print(f"Total supported exchanges: {len(exchanges)}")
        
        # Show some popular ones
        popular = ['binance', 'okx', 'bybit', 'gate', 'huobi', 'kucoin', 
                  'kraken', 'bitget', 'bingx', 'mexc', 'bitfinex']
        print("\nPopular exchanges available:")
        for ex in popular:
            if ex in exchanges:
                print(f"  ✓ {ex}")
        
        # Test exchange validation
        print("\nTesting exchange validation:")
        test_names = ['binance', 'okx', 'invalid_exchange', 'bingx']
        for name in test_names:
            valid = CCXTProcessor.validate_exchange_name(name)
            print(f"  {name}: {'✓ Valid' if valid else '✗ Invalid'}")
        
    except Exception as e:
        print(f"Error listing exchanges: {str(e)}")
    
    # Try to create processor with credentials
    print("\n" + "="*50)
    print("Testing CCXT Processor Initialization")
    print("="*50)
    
    try:
        # This will use the exchange configured in credentials
        async with CCXTProcessor() as processor:
            print(f"\nSuccessfully initialized processor for: {processor.exchange_name}")
            print(f"Enabled: {processor.enabled}")
            print(f"Log Prefix: {processor.log_prefix}")
            
            # Test symbol mapping
            print("\nTesting Symbol Mapping:")
            test_symbols = ["BTCUSDT", "ETHUSDT", "SOLUSDT"]
            for symbol in test_symbols:
                mapped = processor.map_signal_symbol_to_exchange(symbol)
                print(f"  {symbol} -> {mapped}")
            
            # Test market loading
            print("\nLoading Markets...")
            try:
                await processor.exchange.load_markets()
                print(f"Loaded {len(processor.exchange.markets)} markets")
                
                # Show some available perpetual markets
                print("\nSample Perpetual Markets:")
                count = 0
                for symbol, market in processor.exchange.markets.items():
                    if market.get('type') == 'swap' and ':USDT' in symbol:
                        print(f"  {symbol}: active={market.get('active')}")
                        count += 1
                        if count >= 5:
                            break
            except Exception as e:
                print(f"Error loading markets: {str(e)}")
            
            print(f"\n✅ {processor.exchange_name} processor test completed!")
            
    except ValueError as e:
        print(f"\n⚠️  {str(e)}")
        print("\nTo configure a CCXT exchange, run:")
        print("  python config/credentials.py")
        print("\nThen follow the prompts to set up a CCXT-compatible exchange.")
    except Exception as e:
        print(f"\n❌ Error: {str(e)}")
        import traceback
        traceback.print_exc()


async def test_exchange_specific_features():
    """Test exchange-specific features if configured"""
    print("\n" + "="*50)
    print("Testing Exchange-Specific Features")
    print("="*50)
    
    try:
        async with CCXTProcessor() as processor:
            exchange_name = processor.exchange_name.lower()
            
            # Test balance fetching (requires valid API credentials)
            print(f"\nTesting {exchange_name} balance fetch...")
            try:
                balance = await processor.fetch_balance("USDT")
                if balance is not None:
                    print(f"  USDT Balance: {balance}")
                else:
                    print("  No balance found (API credentials may be invalid)")
            except Exception as e:
                print(f"  Error: {str(e)}")
            
            # Test symbol details
            print(f"\nTesting symbol details for BTC/USDT:USDT...")
            try:
                details = await processor.get_symbol_details("BTC/USDT:USDT")
                if details:
                    lot_size, min_size, tick_size, contract_value, max_size = details
                    print(f"  Lot Size: {lot_size}")
                    print(f"  Min Size: {min_size}")
                    print(f"  Tick Size: {tick_size}")
                    print(f"  Contract Value: {contract_value}")
                    print(f"  Max Size: {max_size}")
            except Exception as e:
                print(f"  Error: {str(e)}")
                
    except Exception as e:
        print(f"Could not test exchange-specific features: {str(e)}")


async def main():
    """Main test function"""
    print("CCXT Generic Processor Test Suite")
    print("="*80)
    
    # Run basic tests
    await test_ccxt_processor()
    
    # Run exchange-specific tests
    await test_exchange_specific_features()
    
    print("\n" + "="*80)
    print("Test suite completed!")


if __name__ == "__main__":
    asyncio.run(main()) 