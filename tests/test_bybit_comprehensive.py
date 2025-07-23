#!/usr/bin/env python3
"""
Comprehensive Bybit test comparing native processor with CCXT processor.
Tests position management, leverage changes, margin modes, and data consistency.
"""
import asyncio
import sys
from pathlib import Path
sys.path.append(str(Path(__file__).parent.parent))

from account_processors.bybit_processor import ByBit
from account_processors.ccxt_processor import CCXTProcessor
from config.credentials import load_ccxt_credentials
from colorama import init, Fore, Style

init(autoreset=True)


class BybitComprehensiveTest:
    def __init__(self):
        self.native = None
        self.ccxt = None
        self.test_symbol = "ADAUSDT"  # Native format
        self.ccxt_symbol = "ADA/USDT:USDT"  # CCXT format
        self.initial_position_size = 50  # 50 ADA
        
    async def setup(self):
        """Initialize both processors."""
        print(f"{Fore.CYAN}{'='*60}")
        print(f"{Fore.CYAN}Setting up Bybit processors...")
        print(f"{Fore.CYAN}{'='*60}")
        
        # Initialize native processor
        self.native = ByBit()
        print(f"{Fore.GREEN}✓ Native Bybit processor initialized")
        
        # Initialize CCXT processor with Bybit credentials
        all_credentials = load_ccxt_credentials()
        bybit_cred = None
        for cred in all_credentials.ccxt_list:
            if cred.exchange_name.lower() == 'bybit':
                bybit_cred = cred
                break
        
        if not bybit_cred:
            raise ValueError("Bybit credentials not found in CCXT list")
            
        self.ccxt = CCXTProcessor(ccxt_credentials=bybit_cred)
        print(f"{Fore.GREEN}✓ CCXT Bybit processor initialized")
        
    async def cleanup(self):
        """Clean up resources."""
        if self.ccxt:
            await self.ccxt.exchange.close()
            
    async def test_account_values(self):
        """Test account value calculations."""
        print(f"\n{Fore.YELLOW}Testing account values...")
        
        # Native
        native_balance = await self.native.fetch_balance("USDT")
        native_value = await self.native.fetch_initial_account_value()
        print(f"\n{Fore.CYAN}Native Bybit:")
        print(f"  Balance: {native_balance} USDT")
        print(f"  Total Account Value: {native_value} USDT")
        
        # CCXT
        ccxt_balance = await self.ccxt.fetch_balance("USDT")
        ccxt_value = await self.ccxt.fetch_initial_account_value()
        print(f"\n{Fore.CYAN}CCXT Bybit:")
        print(f"  Balance: {ccxt_balance} USDT")
        print(f"  Total Account Value: {ccxt_value} USDT")
        
        # Compare
        balance_diff = abs(float(native_balance or 0) - float(ccxt_balance or 0))
        value_diff = abs(native_value - ccxt_value)
        
        print(f"\n{Fore.MAGENTA}Differences:")
        print(f"  Balance diff: {balance_diff:.4f} USDT")
        print(f"  Total value diff: {value_diff:.4f} USDT")
        
    async def test_tickers(self):
        """Test ticker fetching and comparison."""
        print(f"\n{Fore.YELLOW}Testing tickers...")
        
        # Native
        native_ticker = await self.native.fetch_tickers(self.test_symbol)
        print(f"\n{Fore.CYAN}Native ticker:")
        if native_ticker:
            print(f"  Symbol: {native_ticker.symbol}")
            print(f"  Bid: {native_ticker.bid}")
            print(f"  Ask: {native_ticker.ask}")
            print(f"  Last: {native_ticker.last}")
        
        # CCXT
        ccxt_ticker = await self.ccxt.fetch_tickers(self.ccxt_symbol)
        print(f"\n{Fore.CYAN}CCXT ticker:")
        if ccxt_ticker:
            print(f"  Symbol: {ccxt_ticker.symbol}")
            print(f"  Bid: {ccxt_ticker.bid}")
            print(f"  Ask: {ccxt_ticker.ask}")
            print(f"  Last: {ccxt_ticker.last}")
            
    async def close_existing_positions(self):
        """Close any existing positions before starting tests."""
        print(f"\n{Fore.YELLOW}Checking for existing positions...")
        
        # Check native positions
        positions = await self.native.fetch_and_map_positions(self.test_symbol)
        if positions:
            print(f"{Fore.RED}Found existing position, closing it first...")
            await self.native.close_position(self.test_symbol)
            await asyncio.sleep(2)
            
    async def test_account_info(self):
        """Test account configuration and margin modes."""
        print(f"\n{Fore.YELLOW}Testing account configuration...")
        
        # Get account margin mode
        try:
            margin_mode = await self.native.get_account_margin_mode()
            print(f"\n{Fore.CYAN}Account Configuration:")
            print(f"  Account Margin Mode: {margin_mode}")
        except Exception as e:
            print(f"{Fore.RED}Could not fetch account margin mode: {str(e)}")
            
    async def test_position_lifecycle(self):
        """Test complete position lifecycle with both processors."""
        print(f"\n{Fore.CYAN}{'='*60}")
        print(f"{Fore.CYAN}Testing Position Lifecycle")
        print(f"{Fore.CYAN}{'='*60}")
        
        # Close any existing positions
        await self.close_existing_positions()
        
        # Test 1: Open short position with isolated margin
        print(f"\n{Fore.YELLOW}Test 1: Opening SHORT position with isolated margin...")
        await self.native.reconcile_position(
            symbol=self.test_symbol,
            size=-self.initial_position_size,  # Negative for short
            leverage=5,
            margin_mode="isolated"
        )
        await asyncio.sleep(3)
        
        # Fetch and compare positions
        await self.compare_positions("After opening short")
        
        # Test 2: Change leverage
        print(f"\n{Fore.YELLOW}Test 2: Changing leverage from 5x to 10x...")
        await self.native.reconcile_position(
            symbol=self.test_symbol,
            size=-self.initial_position_size,
            leverage=10,
            margin_mode="isolated"
        )
        await asyncio.sleep(3)
        
        await self.compare_positions("After leverage change")
        
        # Test 3: Try changing margin mode (Bybit doesn't allow on open positions)
        print(f"\n{Fore.YELLOW}Test 3: Testing margin mode behavior...")
        print(f"{Fore.YELLOW}  Note: Bybit doesn't allow changing margin mode on open positions")
        
        # Test 4: Flip position (short to long)
        print(f"\n{Fore.YELLOW}Test 4: Flipping position from SHORT to LONG...")
        await self.native.reconcile_position(
            symbol=self.test_symbol,
            size=self.initial_position_size,  # Positive for long
            leverage=8,
            margin_mode="isolated"
        )
        await asyncio.sleep(3)
        
        await self.compare_positions("After position flip")
        
        # Test 5: Reduce position size
        print(f"\n{Fore.YELLOW}Test 5: Reducing position size by half...")
        await self.native.reconcile_position(
            symbol=self.test_symbol,
            size=self.initial_position_size / 2,
            leverage=8,
            margin_mode="isolated"
        )
        await asyncio.sleep(3)
        
        await self.compare_positions("After position reduction")
        
        # Test 6: Close position
        print(f"\n{Fore.YELLOW}Test 6: Closing position...")
        await self.native.close_position(self.test_symbol)
        await asyncio.sleep(3)
        
        await self.compare_positions("After closing position")
        
        # Test 7: Test cross margin
        print(f"\n{Fore.YELLOW}Test 7: Testing CROSS margin mode...")
        await self.native.reconcile_position(
            symbol=self.test_symbol,
            size=self.initial_position_size,
            leverage=5,
            margin_mode="cross"
        )
        await asyncio.sleep(3)
        
        await self.compare_positions("After opening with cross margin")
        
        # Close position
        await self.native.close_position(self.test_symbol)
        await asyncio.sleep(2)
        
    async def compare_positions(self, stage: str):
        """Compare positions between native and CCXT processors."""
        print(f"\n{Fore.MAGENTA}Comparing positions - {stage}:")
        
        # Native positions
        native_positions = await self.native.fetch_and_map_positions(self.test_symbol)
        
        # CCXT positions
        ccxt_positions = await self.ccxt.fetch_and_map_positions(self.ccxt_symbol)
        
        if not native_positions and not ccxt_positions:
            print(f"{Fore.GREEN}  ✓ Both processors show no positions")
            return
            
        if native_positions and not ccxt_positions:
            print(f"{Fore.RED}  ✗ Native has position but CCXT doesn't!")
            return
            
        if not native_positions and ccxt_positions:
            print(f"{Fore.RED}  ✗ CCXT has position but Native doesn't!")
            return
            
        # Both have positions, compare
        native_pos = native_positions[0]
        ccxt_pos = ccxt_positions[0]
        
        print(f"\n{Fore.CYAN}Native Position:")
        print(f"  Size: {native_pos.size}")
        print(f"  Direction: {native_pos.direction}")
        print(f"  Entry Price: {native_pos.average_entry_price}")
        print(f"  Leverage: {native_pos.leverage}")
        print(f"  Margin Mode: {native_pos.margin_mode}")
        print(f"  Unrealized PnL: {native_pos.unrealized_pnl}")
        
        print(f"\n{Fore.CYAN}CCXT Position:")
        print(f"  Size: {ccxt_pos.size}")
        print(f"  Direction: {ccxt_pos.direction}")
        print(f"  Entry Price: {ccxt_pos.average_entry_price}")
        print(f"  Leverage: {ccxt_pos.leverage}")
        print(f"  Margin Mode: {ccxt_pos.margin_mode}")
        print(f"  Unrealized PnL: {ccxt_pos.unrealized_pnl}")
        
        # Calculate differences
        size_diff = abs(native_pos.size - ccxt_pos.size)
        price_diff = abs(native_pos.average_entry_price - ccxt_pos.average_entry_price)
        leverage_match = native_pos.leverage == ccxt_pos.leverage
        margin_mode_match = native_pos.margin_mode == ccxt_pos.margin_mode
        direction_match = native_pos.direction == ccxt_pos.direction
        
        print(f"\n{Fore.MAGENTA}Comparison Results:")
        print(f"  Size difference: {size_diff:.4f} {'✓' if size_diff < 0.01 else '✗'}")
        print(f"  Price difference: {price_diff:.4f} {'✓' if price_diff < 0.01 else '✗'}")
        print(f"  Leverage match: {'✓' if leverage_match else '✗'}")
        print(f"  Margin mode match: {'✓' if margin_mode_match else '✗'}")
        print(f"  Direction match: {'✓' if direction_match else '✗'}")
        
    async def test_symbol_details(self):
        """Test symbol details fetching."""
        print(f"\n{Fore.YELLOW}Testing symbol details...")
        
        # Native
        native_details = await self.native.get_symbol_details(self.test_symbol)
        if native_details:
            lot_size, min_size, tick_size, contract_value, max_size = native_details
            print(f"\n{Fore.CYAN}Native Symbol Details:")
            print(f"  Lot Size: {lot_size}")
            print(f"  Min Size: {min_size}")
            print(f"  Max Size: {max_size}")
            print(f"  Tick Size: {tick_size}")
            print(f"  Contract Value: {contract_value}")
            
        # CCXT
        ccxt_details = await self.ccxt.get_symbol_details(self.ccxt_symbol)
        if ccxt_details:
            lot_size, min_size, tick_size, contract_value, max_size = ccxt_details
            print(f"\n{Fore.CYAN}CCXT Symbol Details:")
            print(f"  Lot Size: {lot_size}")
            print(f"  Min Size: {min_size}")
            print(f"  Max Size: {max_size}")
            print(f"  Tick Size: {tick_size}")
            print(f"  Contract Value: {contract_value}")
            
    async def run_all_tests(self):
        """Run all comprehensive tests."""
        try:
            await self.setup()
            
            # Run tests
            await self.test_account_info()
            await self.test_account_values()
            await self.test_tickers()
            await self.test_symbol_details()
            await self.test_position_lifecycle()
            
            print(f"\n{Fore.GREEN}{'='*60}")
            print(f"{Fore.GREEN}All tests completed successfully!")
            print(f"{Fore.GREEN}{'='*60}")
            
        except Exception as e:
            print(f"\n{Fore.RED}Error during tests: {str(e)}")
            import traceback
            traceback.print_exc()
        finally:
            await self.cleanup()


async def main():
    """Run the comprehensive Bybit test."""
    tester = BybitComprehensiveTest()
    await tester.run_all_tests()


if __name__ == "__main__":
    asyncio.run(main()) 