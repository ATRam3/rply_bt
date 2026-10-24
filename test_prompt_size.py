"""
Test what the bot actually sends to Gemini
"""
import MetaTrader5 as mt5
import pandas as pd

def _fetch_mt5_symbol(mt5_symbol: str) -> str | None:
    """Get trading week data"""
    mt5.symbol_select(mt5_symbol, True)
    rates = mt5.copy_rates_from_pos(mt5_symbol, mt5.TIMEFRAME_D1, 0, 14)
    
    if rates is None or len(rates) == 0:
        return None
    
    df = pd.DataFrame(rates)
    df['time'] = pd.to_datetime(df['time'], unit='s')
    df['day_of_week'] = df['time'].dt.dayofweek
    
    all_low = df['low'].min()
    all_high = df['high'].max()
    latest = df['close'].iloc[-1]
    
    weekdays = df[df['day_of_week'] <= 4]
    this_week = weekdays.tail(5)
    last_week = weekdays.iloc[-10:-5] if len(weekdays) >= 10 else weekdays.iloc[:5]
    
    this_low = this_week['low'].min() if len(this_week) > 0 else all_low
    this_high = this_week['high'].max() if len(this_week) > 0 else all_high
    this_start = this_week['time'].iloc[0].strftime('%Y-%m-%d') if len(this_week) > 0 else 'N/A'
    this_end = this_week['time'].iloc[-1].strftime('%Y-%m-%d') if len(this_week) > 0 else 'N/A'
    
    last_low = last_week['low'].min() if len(last_week) > 0 else all_low
    last_high = last_week['high'].max() if len(last_week) > 0 else all_high
    last_start = last_week['time'].iloc[0].strftime('%Y-%m-%d') if len(last_week) > 0 else 'N/A'
    last_end = last_week['time'].iloc[-1].strftime('%Y-%m-%d') if len(last_week) > 0 else 'N/A'

    # Price records
    records = [f"{row['time'].strftime('%Y-%m-%d %A'):25} | Open: {row['open']} | Low: {row['low']} | High: {row['high']} | Close: {row['close']}" 
               for _, row in df.iterrows()]
    
    return (
        f"[{mt5_symbol}] Last 14 daily candles:\n" +
        "\n".join(records) +
        f"\n\n>>> ANSWER KEY <<<\n"
        f"Entire 14-Day Period Lowest Price: {all_low}\n"
        f"Entire 14-Day Period Highest Price: {all_high}\n"
        f"Latest Close Price: {latest}\n\n"
        f"THIS WEEK - Trading Week Mon-Fri ({this_start} to {this_end}):\n"
        f"  This Week's Lowest Price: {this_low}\n"
        f"  This Week's Highest Price: {this_high}\n\n"
        f"LAST WEEK - Previous Trading Week Mon-Fri ({last_start} to {last_end}):\n"
        f"  Last Week's Lowest Price: {last_low}\n"
        f"  Last Week's Highest Price: {last_high}"
    )


if __name__ == "__main__":
    if not mt5.initialize():
        print("MT5 failed")
        exit(1)
    
    # Get data for GBPJPY
    data = _fetch_mt5_symbol("GBPJPYm")
    
    if data:
        print("="*80)
        print("WHAT THE BOT SENDS TO GEMINI:")
        print("="*80)
        print(data)
        print("\n" + "="*80)
        print(f"Prompt size: {len(data)} characters")
        print("="*80)
        
        # Show the actual prompt
        prompt = f"{data}\n\nQuestion in image. Reply with ONLY the answer (number or text). No explanation."
        print("\nFULL PROMPT TO GEMINI:")
        print("="*80)
        print(prompt)
        print("\n" + "="*80)
        print(f"Total prompt: {len(prompt)} characters")
        print("This is MUCH smaller than sending 5 tickers (would be ~4000+ chars)")
        print("="*80)
    
    mt5.shutdown()
