"""
Friday Night Price Generator
----------------------------
Run on the Windows PC that has MT5, on Friday night AFTER the market closes
(after 00:00 broker time, so Friday's daily candle is complete).
It writes mt5_prices.json for the bot (needed on Linux / Codespaces).

    python price_generator.py
"""
import json
import os
import sys
from datetime import datetime

import MetaTrader5 as mt5
import pandas as pd

if sys.stdout.encoding != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8")

OUTPUT_FILE = "mt5_prices.json"
BARS = 30            # enough for this week + last week with margin
STALE_DAYS = 4

SYMBOLS = [
    # MAJORS
    "EURUSDm", "GBPUSDm", "USDJPYm", "USDCHFm", "AUDUSDm", "USDCADm", "NZDUSDm",
    # CROSSES
    "EURJPYm", "GBPJPYm", "EURGBPm", "AUDJPYm", "GBPCHFm", "EURCHFm",
    "AUDNZDm", "AUDCADm", "CADJPYm", "CHFJPYm", "NZDJPYm", "GBPCADm",
    "GBPAUDm", "GBPNZDm", "EURCADm", "EURAUDm", "EURNZDm", "AUDCHFm",
    "NZDCADm", "NZDCHFm", "CADCHFm",
    # COMMODITIES
    "XAUUSDm", "XAGUSDm", "USOILm", "UKOILm",
    # US INDICES
    "US30m", "US500m", "USTECm", "US2000m",
    # EUROPEAN INDICES
    "DE30m", "DE40m", "UK100m", "FR40m", "ES35m", "IT40m", "EU50m",
    # ASIAN INDICES
    "JP225m", "HK50m", "CN50m", "AU200m",
    # CRYPTO
    "BTCUSDm", "ETHUSDm", "LTCUSDm", "XRPUSDm",
]


def strip_suffix(symbol: str) -> str:
    """Remove only the trailing broker 'm' (the old code removed EVERY 'm')."""
    return symbol[:-1] if symbol.endswith("m") else symbol


def get_daily_bars(symbol: str) -> dict | None:
    mt5.symbol_select(symbol, True)
    rates = mt5.copy_rates_from_pos(symbol, mt5.TIMEFRAME_D1, 0, BARS)
    if rates is None or len(rates) == 0:
        return None

    df = pd.DataFrame(rates)
    df["time"] = pd.to_datetime(df["time"], unit="s")
    info = mt5.symbol_info(symbol)

    return {
        "symbol": strip_suffix(symbol),
        "timeframe": "D1",
        "digits": info.digits if info else None,   # the bot formats answers with this
        "bars": [
            {
                "time": row["time"].isoformat(),
                "open": float(row["open"]),
                "high": float(row["high"]),
                "low": float(row["low"]),
                "close": float(row["close"]),
            }
            for _, row in df.iterrows()
        ],
    }


def week_windows(now: pd.Timestamp):
    this_monday = (now - pd.Timedelta(days=now.dayofweek)).normalize()
    last_monday = this_monday - pd.Timedelta(days=7)
    return this_monday, this_monday + pd.Timedelta(days=4), last_monday, last_monday + pd.Timedelta(days=4)


def main():
    print("=" * 60)
    print("Friday Night Price Generator")
    print("=" * 60)

    now = pd.Timestamp.now()
    tm, tf, lm, lf = week_windows(now)
    print(f"Current time : {now}")
    print(f"THIS WEEK    : {tm:%Y-%m-%d} (Mon) -> {tf:%Y-%m-%d} (Fri)")
    print(f"LAST WEEK    : {lm:%Y-%m-%d} (Mon) -> {lf:%Y-%m-%d} (Fri)")
    if now.dayofweek < 4:
        print("⚠️  It is not Friday/weekend yet — this week's candles are incomplete.")
    print()

    if not mt5.initialize():
        print(f"❌ MT5 initialization failed: {mt5.last_error()}")
        return 1
    print("✅ MT5 initialized")

    data = {"generated_at": datetime.now().isoformat(), "prices": []}
    missing = []
    for symbol in SYMBOLS:
        item = get_daily_bars(symbol)
        if item:
            data["prices"].append(item)
            print(f"  ✅ {symbol:<9} last candle {item['bars'][-1]['time'][:10]}")
        else:
            missing.append(symbol)
            print(f"  ⚠️ {symbol:<9} not available on this broker")
    mt5.shutdown()

    if not data["prices"]:
        print("\n❌ No data fetched — nothing saved.")
        return 1

    newest = max(pd.to_datetime(p["bars"][-1]["time"]) for p in data["prices"])
    if now - newest > pd.Timedelta(days=STALE_DAYS):
        print(f"\n🚨 Newest candle is {newest.date()} — MT5 data looks old. Open MT5, let it sync, run again.")

    tmp = OUTPUT_FILE + ".tmp"
    with open(tmp, "w") as f:
        json.dump(data, f, indent=2)
    os.replace(tmp, OUTPUT_FILE)              # never leaves a half-written file

    print()
    print("=" * 60)
    print(f"✅ Saved {OUTPUT_FILE}: {len(data['prices'])} symbols, generated {data['generated_at']}")
    if missing:
        print(f"   Missing: {', '.join(missing)}")
    print("\nNext: git add mt5_prices.json && git commit -m 'Prices for Saturday quiz' && git push")
    print("      then on Codespaces: git pull (or restart the bot so it reloads the file)")
    print("=" * 60)
    return 0


if __name__ == "__main__":
    sys.exit(main())