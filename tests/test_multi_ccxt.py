#!/usr/bin/env python3
"""
Test script to verify multiple CCXT exchanges can be configured and loaded
"""

import asyncio
import sys
import os

# Add parent directory to path to import modules
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config.credentials import load_ccxt_credentials
from account_processors.ccxt_processor import CCXTProcessor


async def test_multi_ccxt():
    """Test loading and initializing multiple CCXT exchanges."""
    print("="*80)
    print("TESTING MULTIPLE CCXT EXCHANGES")
    print("="*80)
    
    try:
        # Load credentials
        credentials = load_ccxt_credentials()
        
        if not credentials.ccxt_list:
            print("No CCXT exchanges configured.")
            print("Run 'python config/credentials.py' to configure CCXT exchanges.")
            return
            
        print(f"\nFound {len(credentials.ccxt_list)} CCXT exchange(s) configured:")
        for i, cred in enumerate(credentials.ccxt_list):
            print(f"{i+1}. {cred.exchange_name} - Enabled: {cred.enabled}")
        
        # Test each exchange
        print("\nTesting each exchange:")
        print("-" * 60)
        
        for cred in credentials.ccxt_list:
            if not cred.enabled:
                print(f"\n{cred.exchange_name}: SKIPPED (disabled)")
                continue
                
            print(f"\n{cred.exchange_name}:")
            try:
                # Create processor with specific credentials
                async with CCXTProcessor(ccxt_credentials=cred) as processor:
                    # Test balance fetching
                    balance = await processor.fetch_balance("USDT")
                    print(f"  Balance: {balance} USDT")
                    
                    # Test account value
                    account_value = await processor.fetch_initial_account_value()
                    print(f"  Account Value: {account_value} USDT")
                    
                    # Test symbol mapping
                    test_symbol = "BTCUSDT"
                    mapped = processor.map_signal_symbol_to_exchange(test_symbol)
                    print(f"  Symbol Mapping: {test_symbol} -> {mapped}")
                    
            except Exception as e:
                print(f"  ERROR: {str(e)}")
        
        # Test creating multiple processors simultaneously
        print("\n" + "="*60)
        print("Testing simultaneous operation of all exchanges:")
        print("-" * 60)
        
        processors = []
        for cred in credentials.ccxt_list:
            if cred.enabled:
                processor = CCXTProcessor(ccxt_credentials=cred)
                processors.append(processor)
        
        if processors:
            # Get balances from all exchanges concurrently
            balance_tasks = [p.fetch_balance("USDT") for p in processors]
            balances = await asyncio.gather(*balance_tasks, return_exceptions=True)
            
            for proc, balance in zip(processors, balances):
                if isinstance(balance, Exception):
                    print(f"{proc.exchange_name}: ERROR - {balance}")
                else:
                    print(f"{proc.exchange_name}: {balance} USDT")
            
            # Clean up
            close_tasks = [p.exchange.close() for p in processors]
            await asyncio.gather(*close_tasks, return_exceptions=True)
        
    except Exception as e:
        print(f"\nError in test: {str(e)}")
        import traceback
        traceback.print_exc()


async def main():
    """Main function"""
    print("Multi-CCXT Test")
    print("This test verifies that multiple CCXT exchanges can be configured and used")
    print("=" * 80)
    
    await test_multi_ccxt()


if __name__ == "__main__":
    asyncio.run(main()) 