import asyncio
import sys
import os
import re
import time
from dotenv import load_dotenv

# Fix Windows terminal encoding so emojis in print() never crash
if sys.stdout.encoding != 'utf-8':
    sys.stdout.reconfigure(encoding='utf-8')

# Load credentials from .env file
load_dotenv()

from io import BytesIO
from pyrogram import Client, filters
from pyrogram.types import Message
import google.genai as genai
from PIL import Image
import MetaTrader5 as mt5
import pandas as pd

# 1. CREDENTIALS (loaded from .env)
API_ID = int(os.getenv("TELEGRAM_API_ID"))
API_HASH = os.getenv("TELEGRAM_API_HASH")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

# 2. TARGET CHANNEL (loaded from .env)
TARGET_CHAT = int(os.getenv("TARGET_CHAT"))

# Initialize Google GenAI Client
client_ai = genai.Client(api_key=GEMINI_API_KEY)

# Initialize Telegram Userbot Session
app = Client("fast_image_userbot", api_id=API_ID, api_hash=API_HASH)

# ── MT5 State ──
_mt5_initialized = False

# ── Pre-warmed symbol cache: mt5_symbol -> (timestamp, data_string) ──
_symbol_cache: dict[str, tuple[float, str]] = {}
_CACHE_TTL = 120  # 2 minutes — daily candles barely change


# ── Expanded Exness symbol map (includes common aliases for indices) ──
SYMBOL_MAP = {
    "GOLD": "XAUUSDm", "XAUUSD": "XAUUSDm",
    "SILVER": "XAGUSDm", "XAGUSD": "XAGUSDm",
    "BTCUSD": "BTCUSDm", "BTC": "BTCUSDm", "BITCOIN": "BTCUSDm",
    "ETHUSD": "ETHUSDm", "ETH": "ETHUSDm", "ETHEREUM": "ETHUSDm",
    "EURUSD": "EURUSDm", "GBPUSD": "GBPUSDm",
    "USDJPY": "USDJPYm", "GBPJPY": "GBPJPYm",
    "EURJPY": "EURJPYm", "AUDUSD": "AUDUSDm",
    "USDCAD": "USDCADm", "USDCHF": "USDCHFm",
    "NZDUSD": "NZDUSDm", "EURGBP": "EURGBPm",
    "EURAUD": "EURAUDm", "GBPAUD": "GBPAUDm",
    "AUDCAD": "AUDCADm", "AUDJPY": "AUDJPYm",
    "CADJPY": "CADJPYm", "CHFJPY": "CHFJPYm",
    "NZDJPY": "NZDJPYm", "GBPCAD": "GBPCADm",
    "GBPCHF": "GBPCHFm", "EURNZD": "EURNZDm",
    "EURCHF": "EURCHFm", "EURCAD": "EURCADm",
    "AUDNZD": "AUDNZDm", "AUDCHF": "AUDCHFm",
    "CADCHF": "CADCHFm", "NZDCAD": "NZDCADm",
    "NZDCHF": "NZDCHFm", "GBPNZD": "GBPNZDm",
    # Indices — many aliases because Gemini says "S&P 500" or "Dow Jones"
    "US30": "US30m", "DJ30": "US30m", "DOW": "US30m", "DOWJONES": "US30m",
    "US500": "US500m", "SP500": "US500m", "SPX": "US500m", "SPX500": "US500m",
    "USTEC": "USTECm", "NAS100": "USTECm", "NASDAQ": "USTECm", "NASDAQ100": "USTECm", "NSDQ": "USTECm",
    "DE30": "DE30m", "DAX": "DE30m", "DE40": "DE40m",
    "UK100": "UK100m", "FTSE": "UK100m",
    "JP225": "JP225m", "NIKKEI": "JP225m",
    "FR40": "FR40m", "HK50": "HK50m",
}

# Reverse lookup: "XAUUSDm" -> "XAUUSD" (for display)
_MT5_TO_TICKER = {}
for _k, _v in SYMBOL_MAP.items():
    if _v not in _MT5_TO_TICKER:
        _MT5_TO_TICKER[_v] = _k


def ensure_mt5(force_retry: bool = False) -> bool:
    """Returns True if MT5 is ready. If force_retry, resets cached state."""
    global _mt5_initialized
    if force_retry:
        _mt5_initialized = False
    if not _mt5_initialized:
        _mt5_initialized = mt5.initialize()
    return _mt5_initialized


def _fetch_mt5_symbol(mt5_symbol: str) -> str | None:
    """Raw MT5 fetch for a single symbol. Returns formatted string or None."""
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


def get_market_data(ticker_symbol: str) -> str | None:
    """Fetch daily candles for a ticker. Uses cache, auto-retries MT5 on failure."""
    try:
        clean = ticker_symbol.strip().upper().replace("/", "").replace("=", "").replace("-", "").replace(" ", "")
        mt5_symbol = SYMBOL_MAP.get(clean, clean if clean.endswith("M") else clean + "m")

        # Cache check
        cached = _symbol_cache.get(mt5_symbol)
        if cached and (time.time() - cached[0]) < _CACHE_TTL:
            return cached[1]

        if not ensure_mt5():
            # One retry in case connection went stale
            if not ensure_mt5(force_retry=True):
                print(f"❌ MT5 unavailable: {mt5.last_error()}")
                return None

        data = _fetch_mt5_symbol(mt5_symbol)
        if data:
            _symbol_cache[mt5_symbol] = (time.time(), data)
            return data
        else:
            print(f"⚠️ Symbol '{mt5_symbol}' not in Market Watch.")
    except Exception as e:
        print(f"❌ MT5 error for {ticker_symbol}: {e}")
    return None


def _pre_warm_cache():
    """Pre-fetch popular symbols at startup so first requests hit cache."""
    if not ensure_mt5():
        return
    # Focus on top 5 most common symbols
    popular = ["XAUUSDm", "GBPJPYm", "EURUSDm", "BTCUSDm", "GBPUSDm"]
    
    print(f"📊 Pre-warming {len(popular)} top symbols...")
    for sym in popular:
        data = _fetch_mt5_symbol(sym)
        if data:
            _symbol_cache[sym] = (time.time(), data)
    print(f"✅ Cache ready")


def _resize_image(img: Image.Image, max_side: int = 768) -> Image.Image:
    """Downsample large images so Gemini upload is faster. Quality stays fine for text."""
    w, h = img.size
    if max(w, h) <= max_side:
        return img
    ratio = max_side / max(w, h)
    return img.resize((int(w * ratio), int(h * ratio)), Image.LANCZOS)


def _clean_answer(raw: str) -> str:
    """Strip markdown formatting and filler from Gemini response."""
    text = raw.strip()
    # Remove markdown bold/italic
    text = re.sub(r'\*+', '', text)
    text = re.sub(r'_+', '', text)
    # Remove common filler prefixes
    for filler in ["The answer is ", "Answer: ", "answer: ", "Result: "]:
        if text.lower().startswith(filler.lower()):
            text = text[len(filler):]
    return text.strip()


def _extract_ticker_from_text(text: str) -> str | None:
    """Try to find a known ticker in Gemini's response using pattern matching."""
    # Strip everything except letters and digits for matching
    clean = text.upper()
    for ch in "/&. ,'\"#()":
        clean = clean.replace(ch, "")
    # Try exact known tickers first (longest first to match NASDAQ100 before NAS100)
    known = sorted(SYMBOL_MAP.keys(), key=len, reverse=True)
    for ticker in known:
        if ticker in clean:
            return ticker
    # Fallback: 6-letter uppercase block that looks like a forex pair
    match = re.search(r'[A-Z]{6}', clean)
    if match:
        return match.group(0)
    # Fallback: alphanumeric block like US500, US30
    match = re.search(r'[A-Z]{2}\d{2,3}', clean)
    if match:
        return match.group(0)
    return None


def solve_question_image(photo_bytes: BytesIO) -> str:
    """Fast two-step: Quick ticker detection → Answer with exact data"""
    try:
        photo_bytes.seek(0)
        img = Image.open(photo_bytes)
        img = _resize_image(img)

        t0 = time.time()
        
        # Step 1: Quick ticker extraction (small image, minimal prompt)
        # Resize even smaller for ticker detection
        small_img = img.copy()
        w, h = small_img.size
        if max(w, h) > 512:
            ratio = 512 / max(w, h)
            small_img = small_img.resize((int(w * ratio), int(h * ratio)), Image.LANCZOS)
        
        try:
            ticker_resp = client_ai.models.generate_content(
                model='gemini-3.5-flash',
                contents=[
                    "What trading symbol is shown? Reply ONLY: XAUUSD or GBPJPY or EURUSD or BTCUSD or GBPUSD",
                    small_img
                ]
            )
            ticker = _extract_ticker_from_text(ticker_resp.text) or "XAUUSD"
        except Exception as e:
            print(f"⚠️ Ticker detection failed, using XAUUSD")
            ticker = "XAUUSD"
        
        t1 = time.time()
        print(f"🔎 Ticker: {ticker} ({t1-t0:.1f}s)")
        
        # Step 2: Get ONLY that ticker's data
        market_data = get_market_data(ticker)
        
        if not market_data:
            print(f"❌ No data for {ticker}")
            return None
        
        # Step 3: Answer with simple, direct prompt
        prompt = (
            f"{market_data}\n\n"
            "Question in image. Reply with ONLY the answer (number or text). No explanation."
        )

        response = client_ai.models.generate_content(
            model='gemini-3.5-flash',
            contents=[prompt, img]
        )
        
        answer = _clean_answer(response.text)
        total_time = time.time() - t0
        print(f"⚡ Total {total_time:.1f}s | Answer: {answer}")
        return answer

    except Exception as e:
        error_str = str(e)
        print(f"❌ solve_question_image error: {error_str}")
        
        # Handle specific API errors
        if "PERMISSION_DENIED" in error_str or "403" in error_str:
            print("🚨 CRITICAL: Your Gemini API key has been denied access!")
            print("   Solutions:")
            print("   1. Get a new API key from: https://aistudio.google.com/apikey")
            print("   2. Check billing status at: https://console.cloud.google.com/billing")
            print("   3. Verify project quotas at: https://console.cloud.google.com/apis/dashboard")
            return None
        
        # If rate limited, return None so we don't post garbage
        if "RESOURCE_EXHAUSTED" in error_str or "429" in error_str:
            print("⏳ Rate limited — will skip this post.")
            return None
        
        return None


# ==========================================
# LISTEN STRICTLY FOR IMAGES ONLY IN TARGET CHAT
# ==========================================
@app.on_message(filters.chat(TARGET_CHAT) & filters.photo)
async def handle_incoming_post(client: Client, message: Message):
    t_start = time.time()
    print(f"\n⚡ [IMAGE POST #{message.id}] Processing...")

    answer = None
    try:
        # Download with aggressive timeout (faster failure if network is slow)
        photo_file = await asyncio.wait_for(
            client.download_media(message, in_memory=True),
            timeout=5.0
        )
        t_download = time.time() - t_start
        print(f"📸 Downloaded in {t_download:.1f}s")

        # Run blocking Gemini+MT5 work in a thread so Telegram stays responsive
        answer = await asyncio.to_thread(solve_question_image, photo_file)
    except asyncio.TimeoutError:
        print(f"❌ Download timeout (>5s) — skipped.")
        return
    except Exception as e:
        print(f"❌ Photo handling error: {e}")

    if not answer:
        print("⚠️ No answer — skipped.")
        return

    # Post reply immediately (no retry loop to save time)
    try:
        await client.send_message(
            chat_id=message.chat.id,
            text=answer,
            reply_to_message_id=message.id
        )
        print(f"🚀 [TOTAL TIME: {time.time()-t_start:.1f}s]")
    except Exception as e:
        print(f"❌ Send failed: {e}")


if __name__ == "__main__":
    print("🤖 Initializing MT5 connection...")
    if mt5.initialize():
        _mt5_initialized = True
        print("✅ MT5 Connected!")
        print("📊 Pre-warming cache...")
        _pre_warm_cache()
    else:
        print(f"⚠️ MT5 Warning: {mt5.last_error()}")

    print(f"🤖 Listening for images on {TARGET_CHAT}...")
    app.run()

    mt5.shutdown()