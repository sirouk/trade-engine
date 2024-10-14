import asyncio
import datetime
from pybit.unified_trading import HTTP # https://github.com/bybit-exchange/pybit/
from core.credentials import load_bybit_credentials
from core.utils.modifiers import round_to_tick_size, calculate_lots
from core.unified_position import UnifiedPosition
from core.unified_ticker import UnifiedTicker


class ByBit:
    def __init__(self):
        
        self.exchange_name = "ByBit"
            
        # Load Bybit API key and secret from your credentials file
        self.credentials = load_bybit_credentials()

        self.TESTNET = False  # Change to False for production
        self.SETTLE_COIN = "USDT"

        # Initialize the Bybit client
        self.bybit_client = HTTP(
            api_key=self.credentials.bybit.api_key,
            api_secret=self.credentials.bybit.api_secret,
            testnet=self.TESTNET
        )


    async def fetch_balance(self, instrument="USDT"):
        try:
            balance = self.bybit_client.get_wallet_balance(accountType="UNIFIED", settleCoin=self.SETTLE_COIN, coin=instrument)
            # {'retCode': 0, 'retMsg': 'OK', 'result': {'list': [{'totalEquity': '0.10204189', 'accountIMRate': '0', 'totalMarginBalance': '0.09302213', 'totalInitialMargin': '0', 'accountType': 'UNIFIED', 'totalAvailableBalance': '0.09302213', 'accountMMRate': '0', 'totalPerpUPL': '0', 'totalWalletBalance': '0.09302213', 'accountLTV': '0', 'totalMaintenanceMargin': '0', 'coin': [{'availableToBorrow': '', 'bonus': '0', 'accruedInterest': '0', 'availableToWithdraw': '0.09304419', 'totalOrderIM': '0', 'equity': '0.09304419', 'totalPositionMM': '0', 'usdValue': '0.09302213', 'unrealisedPnl': '0', 'collateralSwitch': True, 'spotHedgingQty': '0', 'borrowAmount': '0.000000000000000000', 'totalPositionIM': '0', 'walletBalance': '0.09304419', 'cumRealisedPnl': '-10924.04925374', 'locked': '0', 'marginCollateral': True, 'coin': 'USDT'}]}]}, 'retExtInfo': {}, 'time': 1728795935267}
            
            # get coin balance available to trade
            balance = balance["result"]["list"][0]["coin"][0]["availableToWithdraw"]
            print(f"Account Balance for {instrument}: {balance}")
            return balance
        except Exception as e:
            print(f"Error fetching balance: {str(e)}")

    async def fetch_open_positions(self, symbol):
        try:
            positions = self.bybit_client.get_positions(category="linear", settleCoin=self.SETTLE_COIN, symbol=symbol)
            print(f"Open Positions: {positions}")
            return positions
        except Exception as e:
            print(f"Error fetching open positions: {str(e)}")

    async def fetch_open_orders(self, symbol):
        try:
            orders = self.bybit_client.get_open_orders(category="linear", settleCoin=self.SETTLE_COIN, symbol=symbol)
            print(f"Open Orders: {orders}")
            return orders
        except Exception as e:
            print(f"Error fetching open orders: {str(e)}")

    async def fetch_tickers(self, symbol):
        try:
            tickers = self.bybit_client.get_tickers(category="linear", symbol=symbol)
            ticker_data = tickers["result"]["list"][0]  # Assuming the first entry is the relevant ticker
            
            print(f"Ticker: {ticker_data}")
            return UnifiedTicker(
                symbol=symbol,
                bid=float(ticker_data.get("bid1Price", 0)),
                ask=float(ticker_data.get("ask1Price", 0)),
                last=float(ticker_data.get("lastPrice", 0)),
                volume=float(ticker_data.get("volume24h", 0)),
                exchange=self.exchange_name
            )
        except Exception as e:
            print(f"Error fetching tickers from Bybit: {str(e)}")

    async def get_symbol_details(self, symbol: str):
        """Fetch instrument details including tick size, lot size, min size, and contract value."""
        instruments = self.bybit_client.get_instruments_info(category="linear", symbol=symbol)

        for instrument in instruments["result"]["list"]:
            if instrument["symbol"] == symbol:
                #print(f"Instrument: {instrument}")
                lot_size = float(instrument["lotSizeFilter"]["qtyStep"])
                min_size = float(instrument["lotSizeFilter"]["minOrderQty"])
                tick_size = float(instrument["priceFilter"]["tickSize"])
                contract_value = float(lot_size / min_size)  # Optional fallback

                return lot_size, min_size, tick_size, contract_value
        raise ValueError(f"Symbol {symbol} not found.")

    async def scale_size_and_price(self, symbol: str, size: float, price: float):
        """Scale size and price to match exchange requirements."""
        
        # Fetch symbol details (e.g., contract value, lot size, tick size)
        lot_size, min_lots, tick_size, contract_value = await self.get_symbol_details(symbol)
        print(f"Symbol {symbol} -> Lot Size: {lot_size}, Min Size: {min_lots}, Tick Size: {tick_size}, Contract Value: {contract_value}")
        
        # Step 1: Calculate the number of lots required
        print(f"Desired size: {size}")
        size_in_lots = calculate_lots(size, contract_value)
        print(f"Size in lots: {size_in_lots}")

        # Step 2: Ensure the size meets the minimum size requirement
        size_in_lots = max(size_in_lots, min_lots)
        print(f"Size after checking min: {size_in_lots}")

        # Step 3: Round the price to the nearest tick size
        print(f"Price before: {price}")
        price = round_to_tick_size(price, tick_size)
        print(f"Price after tick rounding: {price}")

        return size_in_lots, price

    async def place_limit_order(self,):
        """Place a limit order on Bybit."""
        try:
            
            # Test limit order
            # https://bybit-exchange.github.io/docs/v5/order/create-order
            # NOTE: make sure margin type is set to isolated
            # NOTE: leverage must be set separately
            # TODO: size_in_settle_coin = price * size * leverage
            category="linear"
            symbol="BTCUSDT"
            side="Buy"
            price=62699
            size=0.003 # in quantity of symbol
            leverage=3
            isLeverage=1 # 1:leveraged 2: not leveraged
            order_type="Limit"
            time_in_force="IOC"
            margin_mode='ISOLATED_MARGIN' # ISOLATED_MARGIN, REGULAR_MARGIN(i.e. Cross margin), PORTFOLIO_MARGIN
            reduce_only=False
            close_on_trigger=False
            client_oid = datetime.datetime.now().strftime("%Y%m%d%H%M%S%f")
            
            # Fetch and scale the size and price
            lots, price = await self.scale_size_and_price(symbol, size, price)
            print(f"Ordering {lots} lots @ {price}")
            #quit()
            
            # set leverage and margin mode    
            try:
                self.bybit_client.set_margin_mode(
                    setMarginMode=margin_mode,
                )   
            except Exception as e:
                print(f"Margin Mode unchanged: {str(e)}")
            
            try:     
                self.bybit_client.set_leverage(
                    symbol=symbol, 
                    category=category,                
                    buyLeverage=str(leverage), 
                    sellLeverage=str(leverage),
                )
            except Exception as e:
                print(f"Leverage unchanged: {str(e)}")
            
            order = self.bybit_client.place_order(
                category=category,
                symbol=symbol,
                side=side,
                price=price,
                qty=lots,
                isLeverage=isLeverage,
                order_type=order_type,
                time_in_force=time_in_force, # GTC, IOC, FOK, PostOnly (use IOK)
                reduce_only=reduce_only,
                close_on_trigger=close_on_trigger,
                orderLinkId=client_oid,
                positionIdx=0, # one-way mode
            )
            print(f"Limit Order Placed: {order}")
            # Limit Order Placed: {'retCode': 0, 'retMsg': 'OK', 'result': {'orderId': '2c9eee09-b90e-47eb-ace0-d82c6cdc7bfa', 'orderLinkId': '20241014022046505544'}, 'retExtInfo': {}, 'time': 1728872447805}
            # Controlling 0.001 of BTC $62,957.00 is expected to be 62.957 USDT
            # Actual Margin Used: 12.6185 USDT @ 5x 
            return order
            
        except Exception as e:
            print(f"Error placing limit order: {str(e)}")

    def map_bybit_position_to_unified(self, position: dict) -> UnifiedPosition:
        """Convert a Bybit position response into a UnifiedPosition object."""
        size = abs(float(position.get("size", 0)))
        direction = "long" if position.get("side", "").lower() == "buy" else "short"

        return UnifiedPosition(
            symbol=position["symbol"],
            size=size,
            average_entry_price=float(position.get("avgPrice", 0)),
            leverage=float(position.get("leverage", 1)),
            direction=direction,
            unrealized_pnl=float(position.get("unrealisedPnl", 0)),
            exchange=self.exchange_name,
        )

    async def fetch_and_map_positions(self, symbol: str):
        """Fetch open positions from Bybit and convert them to UnifiedPosition objects."""
        try:
            response = self.bybit_client.get_positions(category="linear", settleCoin=self.SETTLE_COIN, symbol=symbol)
            positions = response.get("result", {}).get("list", [])

            unified_positions = [
                self.map_bybit_position_to_unified(pos) 
                for pos in positions 
                if float(pos.get("size", 0)) > 0
            ]

            for unified_position in unified_positions:
                print(f"Unified Position: {unified_position}")
            
            return unified_positions
        except Exception as e:
            print(f"Error mapping Bybit positions: {str(e)}")
            return []


async def main():   
    
    # Start a time
    start_time = datetime.datetime.now()
    
    bybit = ByBit()
    
    # balance = await bybit.fetch_balance(instrument="USDT")      # Fetch futures balance
    # print(balance)
    
    # tickers = await bybit.fetch_tickers(symbol="BTCUSDT")  # Fetch market tickers
    # print(tickers)
    
    order_results = await bybit.place_limit_order()
    print(order_results)
    
    # orders = await bybit.fetch_open_orders(symbol="BTCUSDT")          # Fetch open orders
    # print(orders)

    #await bybit.fetch_open_positions(symbol="BTC-USDT")       # Fetch open positions
    #positions = await bybit.fetch_and_map_positions(symbol="BTCUSDT")
    #print(positions)
    
    # End time
    end_time = datetime.datetime.now()
    print(f"Time taken: {end_time - start_time}")
    
if __name__ == "__main__":
    asyncio.run(main())
