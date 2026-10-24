"""
Test the fixed weekly price calculation
"""
import MetaTrader5 as mt5
import pandas as pd

def _fetch_mt5_symbol(mt5_symbol: str) -> str | None:
    """Fixed version with weekly breakdown"""
    mt5.symbol_select(mt5_symbol, True)
    rates = mt5.copy_rates_from_pos(mt5_symbol, mt5.TIMEFRAME_D1, 0, 14)

    if rates is None or len(rates) == 0:
        return None

    df = pd.DataFrame(rates)
    df['time'] = pd.to_datetime(df['time'], unit='s')

    # Use full clear labels so Gemini can reliably identify Open/Low/High/Close
    price_records = [
        f"{row['time'].strftime('%Y-%m-%d')} | Open: {row['open']} | Low: {row['low']} | High: {row['high']} | Close: {row['close']}"
        for _, row in df.iterrows()
    ]
    
    # Calculate for different time periods
    all_period_low = df['low'].min()
    all_period_high = df['high'].max()
    latest_close = df['close'].iloc[-1]
    
    # THIS WEEK = Last 7 days (most recent)
    this_week_df = df.tail(7)
    this_week_low = this_week_df['low'].min()
    this_week_high = this_week_df['high'].max()
    this_week_start = this_week_df['time'].iloc[0].strftime('%Y-%m-%d')
    this_week_end = this_week_df['time'].iloc[-1].strftime('%Y-%m-%d')
    
    # LAST WEEK = Days 7-13 ago (previous 7 days)
    last_week_df = df.iloc[-14:-7] if len(df) >= 14 else df.iloc[:7]
    last_week_low = last_week_df['low'].min()
    last_week_high = last_week_df['high'].max()
    last_week_start = last_week_df['time'].iloc[0].strftime('%Y-%m-%d')
    last_week_end = last_week_df['time'].iloc[-1].strftime('%Y-%m-%d')

    return (
        f"[{mt5_symbol}] Last 14 daily candles:\n" +
        "\n".join(price_records) +
        f"\n\n>>> ANSWER KEY <<<\n"
        f"Entire 14-Day Period Lowest Price: {all_period_low}\n"
        f"Entire 14-Day Period Highest Price: {all_period_high}\n"
        f"Latest Close Price: {latest_close}\n\n"
        f"THIS WEEK ({this_week_start} to {this_week_end}):\n"
        f"  This Week's Lowest Price: {this_week_low}\n"
        f"  This Week's Highest Price: {this_week_high}\n\n"
        f"LAST WEEK ({last_week_start} to {last_week_end}):\n"
        f"  Last Week's Lowest Price: {last_week_low}\n"
        f"  Last Week's Highest Price: {last_week_high}"
    )


if __name__ == "__main__":
    if not mt5.initialize():
        print(f"MT5 initialization failed: {mt5.last_error()}")
        exit(1)
    
    print("="*80)
    print("TESTING FIXED WEEKLY CALCULATION")
    print("="*80)
    
    for symbol in ["XAUUSDm", "GBPJPYm"]:
        print(f"\n{symbol}:")
        print("-"*80)
        result = _fetch_mt5_symbol(symbol)
        if result:
            print(result)
        else:
            print("Failed to fetch data")
        print()
    
    mt5.shutdown()
