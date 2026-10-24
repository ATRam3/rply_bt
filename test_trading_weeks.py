"""
Test the fixed trading week calculation (Monday-Friday only)
"""
import MetaTrader5 as mt5
import pandas as pd

def _fetch_mt5_symbol(mt5_symbol: str) -> str | None:
    """Fixed version with trading week breakdown"""
    mt5.symbol_select(mt5_symbol, True)
    rates = mt5.copy_rates_from_pos(mt5_symbol, mt5.TIMEFRAME_D1, 0, 14)

    if rates is None or len(rates) == 0:
        return None

    df = pd.DataFrame(rates)
    df['time'] = pd.to_datetime(df['time'], unit='s')
    df['day_of_week'] = df['time'].dt.dayofweek  # Monday=0, Sunday=6

    # Use full clear labels so Gemini can reliably identify Open/Low/High/Close
    price_records = [
        f"{row['time'].strftime('%Y-%m-%d %A'):25} | Open: {row['open']} | Low: {row['low']} | High: {row['high']} | Close: {row['close']}"
        for _, row in df.iterrows()
    ]
    
    # Calculate for different time periods
    all_period_low = df['low'].min()
    all_period_high = df['high'].max()
    latest_close = df['close'].iloc[-1]
    
    # Find the most recent Friday (end of this trading week)
    # If today is Monday-Friday, "this week" = current Mon-Fri
    # We work backwards from the latest data to find complete weeks
    
    # Get the most recent Friday or latest trading day
    latest_date = df['time'].iloc[-1]
    latest_dow = df['day_of_week'].iloc[-1]
    
    # THIS WEEK = Most recent Monday-Friday period (5 trading days)
    # Find the most recent Monday
    this_week_df = df[df['day_of_week'] <= 4].tail(5)  # Monday(0) to Friday(4), last 5 days
    
    # LAST WEEK = Previous Monday-Friday period (5 trading days before this week)
    # Get all Monday-Friday days, then take the 5 before this week
    weekdays_only = df[df['day_of_week'] <= 4]  # Only Mon-Fri
    if len(weekdays_only) >= 10:
        last_week_df = weekdays_only.iloc[-10:-5]  # 5 days before the last 5
    else:
        last_week_df = weekdays_only.iloc[:5] if len(weekdays_only) >= 5 else weekdays_only
    
    # Calculate weekly stats
    this_week_low = this_week_df['low'].min() if len(this_week_df) > 0 else all_period_low
    this_week_high = this_week_df['high'].max() if len(this_week_df) > 0 else all_period_high
    this_week_start = this_week_df['time'].iloc[0].strftime('%Y-%m-%d') if len(this_week_df) > 0 else 'N/A'
    this_week_end = this_week_df['time'].iloc[-1].strftime('%Y-%m-%d') if len(this_week_df) > 0 else 'N/A'
    
    last_week_low = last_week_df['low'].min() if len(last_week_df) > 0 else all_period_low
    last_week_high = last_week_df['high'].max() if len(last_week_df) > 0 else all_period_high
    last_week_start = last_week_df['time'].iloc[0].strftime('%Y-%m-%d') if len(last_week_df) > 0 else 'N/A'
    last_week_end = last_week_df['time'].iloc[-1].strftime('%Y-%m-%d') if len(last_week_df) > 0 else 'N/A'

    return (
        f"[{mt5_symbol}] Last 14 daily candles:\n" +
        "\n".join(price_records) +
        f"\n\n>>> ANSWER KEY <<<\n"
        f"Entire 14-Day Period Lowest Price: {all_period_low}\n"
        f"Entire 14-Day Period Highest Price: {all_period_high}\n"
        f"Latest Close Price: {latest_close}\n\n"
        f"THIS WEEK - Trading Week Mon-Fri ({this_week_start} to {this_week_end}):\n"
        f"  This Week's Lowest Price: {this_week_low}\n"
        f"  This Week's Highest Price: {this_week_high}\n\n"
        f"LAST WEEK - Previous Trading Week Mon-Fri ({last_week_start} to {last_week_end}):\n"
        f"  Last Week's Lowest Price: {last_week_low}\n"
        f"  Last Week's Highest Price: {last_week_high}"
    )


if __name__ == "__main__":
    if not mt5.initialize():
        print(f"MT5 initialization failed: {mt5.last_error()}")
        exit(1)
    
    print("="*80)
    print("TESTING FIXED TRADING WEEK CALCULATION (Monday-Friday Only)")
    print("="*80)
    
    for symbol in ["GBPJPYm", "XAUUSDm"]:
        print(f"\n{symbol}:")
        print("-"*80)
        result = _fetch_mt5_symbol(symbol)
        if result:
            print(result)
        else:
            print("Failed to fetch data")
        print()
    
    mt5.shutdown()
