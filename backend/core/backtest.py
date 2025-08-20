import pandas as pd
import asyncio
from core.strategy import Strategy

class MockConnectionManager:
    """A mock manager to simulate WebSocket broadcasting by printing to console."""
    async def broadcast(self, message: dict):
        # In a real backtest, you might log this to a file or a results object.
        # For simplicity, we'll print some key messages.
        if message['type'] == 'debug_log':
            payload = message['payload']
            # print(f"DEBUG [{payload['source']}]: {payload['message']}")
            pass # Suppress most debug logs for a cleaner report
        elif message['type'] == 'trade_log_update':
            print("--- TRADE LOG UPDATED ---")
        
class MockTickerManager:
    """A mock ticker manager that does nothing, as we control the ticks."""
    def resubscribe(self, tokens):
        pass

async def run_backtest(data_path: str, params: dict):
    print("--- Starting Backtest ---")
    
    # 1. Load Historical Data
    try:
        hist_df = pd.read_csv(
            data_path, 
            parse_dates=['date'], 
            index_col='date'
        )
        print(f"Loaded {len(hist_df)} historical candles from {data_path}")
    except FileNotFoundError:
        print(f"ERROR: Historical data file not found at '{data_path}'")
        return

    # 2. Setup Strategy with Mock Dependencies
    mock_manager = MockConnectionManager()
    strategy = Strategy(
        params=params, 
        manager=mock_manager, 
        selected_index=params.get("selectedIndex", "SENSEX")
    )
    # This flag tells the strategy to not make live API calls
    strategy.is_backtest = True 
    strategy.ticker_manager = MockTickerManager()

    # 3. Bootstrap strategy with our historical data instead of fetching
    await strategy.bootstrap_data(df=hist_df.head(300))
    
    # 4. Simulation Loop
    print("\n--- Running Simulation ---")
    data_to_simulate = hist_df.iloc[300:]
    total_candles = len(data_to_simulate)

    for i, (timestamp, candle) in enumerate(data_to_simulate.iterrows()):
        # Simulate high-frequency ticks within the 1-minute candle
        # This order (O->L->H->C) is a common pessimistic simulation
        ticks_to_process = [
            {'price': candle['open'], 'is_new_minute': True},
            {'price': candle['low'], 'is_new_minute': False},
            {'price': candle['high'], 'is_new_minute': False},
            {'price': candle['close'], 'is_new_minute': False}
        ]
        
        for tick in ticks_to_process:
            # Update the mock price
            strategy.prices[strategy.index_symbol] = tick['price']
            if strategy.position:
                strategy.prices[strategy.position['symbol']] = tick['price'] # Mock option price

            # If it's the start of a new candle, run the main logic
            if tick['is_new_minute']:
                await strategy.update_candle_and_indicators(tick['price'])
            
            # Evaluate exit on every simulated tick
            if strategy.position:
                await strategy.evaluate_exit_logic()

        if (i + 1) % 5000 == 0:
            print(f"Processed {i+1}/{total_candles} candles...")

    print("--- Simulation Complete ---\n")

    # 5. Print Performance Report
    stats = strategy.performance_stats
    total_trades = stats['total_trades']
    if total_trades == 0:
        print("No trades were executed during the backtest period.")
        return

    pnl_values = [float(trade[5]) for trade in strategy.trade_log]
    total_pnl = sum(pnl_values)
    winning_trades = stats['winning_trades']
    losing_trades = stats['losing_trades']
    win_rate = (winning_trades / total_trades) * 100 if total_trades > 0 else 0
    
    gross_profit = sum(p for p in pnl_values if p > 0)
    gross_loss = abs(sum(p for p in pnl_values if p < 0))
    profit_factor = gross_profit / gross_loss if gross_loss > 0 else float('inf')

    print("------ Backtest Performance Report ------")
    print(f"Total Net P&L:      ₹{total_pnl:,.2f}")
    print(f"Total Trades:       {total_trades}")
    print(f"Win Rate:           {win_rate:.2f}%")
    print(f"Profit Factor:      {profit_factor:.2f}")
    print(f"Winning Trades:     {winning_trades}")
    print(f"Losing Trades:      {losing_trades}")
    print("---------------------------------------")
    print("\nTrade Log:")
    for trade in strategy.trade_log:
        print(f"- {trade[1]} | {trade[0]} | Trigger: {trade[2]} | P&L: {float(trade[5]):.2f}")


if __name__ == "__main__":
    # --- CONFIGURATION ---
    # 1. Define the path to your historical data CSV file.
    #    The CSV must have columns: 'date', 'open', 'high', 'low', 'close'
    HISTORICAL_DATA_CSV_PATH = "sensex_historical_data.csv"

    # 2. Define the parameters to test. These should match the frontend.
    BACKTEST_PARAMS = { 
        "selectedIndex": "SENSEX", 
        "trading_mode": "Paper Trading", # Does not matter in backtest
        "aggressiveness": "Moderate", 
        "start_capital": 50000,
        "risk_per_trade_percent": 1.0,
        "trailing_sl_points": 40, 
        "trailing_sl_percent": 10, 
        "daily_sl": -2000, 
        "daily_pt": 4000
    }
    
    asyncio.run(run_backtest(HISTORICAL_DATA_CSV_PATH, BACKTEST_PARAMS))