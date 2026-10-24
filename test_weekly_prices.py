"""
Test script to verify weekly price calculations
"""
import MetaTrader5 as mt5
import pandas as pd
from datetime import datetime, timedelta

def test_weekly_prices(symbol="XAUUSDm"):
    """Test how the bot calculates weekly vs period prices"""
    
    if not mt5.initialize():
        print(f"MT5 initialization failed: {mt5.last_error()}")
        return
    
    mt5.symbol_select(symbol, True)
    rates = mt5.copy_rates_from_pos(symbol, mt5.TIMEFRAME_D1, 0, 14)
    
    if rates is None or len(rates) == 0:
        print("No data received")
        return
    
    df = pd.DataFrame(rates)
    df['time'] = pd.to_datetime(df['time'], unit='s')
    df['day_of_week'] = df['time'].dt.day_name()
    
    print(f"\n{'='*80}")
    print(f"TESTING: {symbol}")
    print(f"{'='*80}\n")
    
    # Show all data
    print("All 14 Days Data:")
    print("-" * 80)
    for idx, row in df.iterrows():
        print(f"{row['time'].strftime('%Y-%m-%d %A'):25} | "
              f"Open: {row['open']:8.2f} | "
              f"Low: {row['low']:8.2f} | "
              f"High: {row['high']:8.2f} | "
              f"Close: {row['close']:8.2f}")
    
    # Current implementation (ALL 14 days)
    print(f"\n{'='*80}")
    print("CURRENT BOT CALCULATION (All 14 days):")
    print(f"{'='*80}")
    period_low = df['low'].min()
    period_high = df['high'].max()
    latest_close = df['close'].iloc[-1]
    print(f"Period Lowest:  {period_low:.2f}")
    print(f"Period Highest: {period_high:.2f}")
    print(f"Latest Close:   {latest_close:.2f}")
    
    # Split by weeks
    print(f"\n{'='*80}")
    print("WEEKLY BREAKDOWN:")
    print(f"{'='*80}")
    
    # Get the most recent complete week (last 7 days excluding today if incomplete)
    today = df['time'].iloc[-1]
    
    # This week (most recent 7 days)
    this_week_df = df.tail(7)
    print(f"\nTHIS WEEK (Last 7 days: {this_week_df['time'].iloc[0].strftime('%Y-%m-%d')} to {this_week_df['time'].iloc[-1].strftime('%Y-%m-%d')}):")
    print(f"  Lowest:  {this_week_df['low'].min():.2f}")
    print(f"  Highest: {this_week_df['high'].max():.2f}")
    
    # Previous week (days 7-13)
    if len(df) >= 14:
        last_week_df = df.iloc[-14:-7]
        print(f"\nLAST WEEK (Days 7-13 ago: {last_week_df['time'].iloc[0].strftime('%Y-%m-%d')} to {last_week_df['time'].iloc[-1].strftime('%Y-%m-%d')}):")
        print(f"  Lowest:  {last_week_df['low'].min():.2f}")
        print(f"  Highest: {last_week_df['high'].max():.2f}")
    
    mt5.shutdown()


if __name__ == "__main__":
    print("Testing Gold (XAUUSD)...")
    test_weekly_prices("XAUUSDm")
    
    print("\n" + "="*80)
    print("\nTesting GBPJPY...")
    test_weekly_prices("GBPJPYm")
