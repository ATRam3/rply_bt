import asyncio
import sys
import os
import re
import time
import json
import logging
from datetime import datetime
from dotenv import load_dotenv

# ── Logging ──────────────────────────────────────────────────────────────
# INFO level so we see Pyrogram's peer-resolution and connection messages.
# Suppress only the noisy "Peer id invalid" DEBUG-level noise.
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("bot")
# Keep Pyrogram at WARNING so we see reconnect/auth issues but not every RPC
logging.getLogger("pyrogram").setLevel(logging.WARNING)

# Fix Windows terminal encoding so emojis in print() never crash
if sys.stdout.encoding != 'utf-8':
    sys.stdout.reconfigure(encoding='utf-8')

# Load credentials from .env file
load_dotenv()

from io import BytesIO
from pyrogram import Client, filters
from pyrogram.types import Message
from pyrogram.errors import FloodWait, ChannelPrivate, PeerIdInvalid
import google.genai as genai
from PIL import Image, ImageFilter
import pandas as pd

# Try to import MT5 (only works on Windows)
try:
    import MetaTrader5 as mt5
    MT5_AVAILABLE = True
    print("✅ MT5: Available (Windows)")
except ImportError:
    MT5_AVAILABLE = False
    mt5 = None
    print("⚠️ MT5: Not available (Linux/Mac - using JSON fallback)")

# OCR for fast text extraction
try:
    import pytesseract
    if os.name == 'nt':  # Windows
        possible_paths = [
            r'C:\Program Files\Tesseract-OCR\tesseract.exe',
            r'C:\Program Files (x86)\Tesseract-OCR\tesseract.exe',
            r'C:\Tesseract-OCR\tesseract.exe'
        ]
        for path in possible_paths:
            if os.path.exists(path):
                pytesseract.pytesseract.tesseract_cmd = path
                break
    OCR_AVAILABLE = True
    print("✅ OCR Mode: Enabled (pytesseract)")
except ImportError:
    OCR_AVAILABLE = False
    print("⚠️ OCR Mode: Disabled (pytesseract not installed)")

# ── Credentials ──────────────────────────────────────────────────────────
API_ID = int(os.getenv("TELEGRAM_API_ID"))
API_HASH = os.getenv("TELEGRAM_API_HASH")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

# ── Target channels ──────────────────────────────────────────────────────
TARGET_CHANNEL = int(os.getenv("TARGET_CHANNEL").strip())  # Main quiz channel
TARGET_CHAT = int(os.getenv("TARGET_CHAT").strip())         # Discussion group

# Initialize Google GenAI Client
client_ai = genai.Client(api_key=GEMINI_API_KEY)

# ── Telegram Userbot ─────────────────────────────────────────────────────
# no_updates=False (default) is CRITICAL: it enables the update dispatcher.
# sleep_threshold=20 means Pyrogram auto-sleeps on FloodWait ≤ 20s.
app = Client(
    "fast_image_userbot",
    api_id=API_ID,
    api_hash=API_HASH,
    sleep_threshold=20,
)

# ── MT5 State ────────────────────────────────────────────────────────────
_mt5_initialized = False

# ── Pre-warmed symbol cache: mt5_symbol -> (timestamp, data_string) ──
_symbol_cache: dict[str, tuple[float, str]] = {}
_CACHE_TTL = 120  # 2 minutes — daily candles barely change

# ── Dedup set for the polling fallback ───────────────────────────────────
# Stores message IDs we've already processed (from either push or poll).
_processed_ids: set[int] = set()
_PROCESSED_MAX = 500  # cap to avoid unbounded growth


# ── Expanded Exness symbol map ───────────────────────────────────────────
SYMBOL_MAP = {
    # === COMMODITIES ===
    "GOLD": "XAUUSDm", "XAUUSD": "XAUUSDm",
    "SILVER": "XAGUSDm", "XAGUSD": "XAGUSDm",
    "USOIL": "USOILm", "OIL": "USOILm", "CRUDE": "USOILm", "WTI": "USOILm",
    "UKOIL": "UKOILm", "BRENT": "UKOILm",

    # === CRYPTO ===
    "BTCUSD": "BTCUSDm", "BTC": "BTCUSDm", "BITCOIN": "BTCUSDm",
    "ETHUSD": "ETHUSDm", "ETH": "ETHUSDm", "ETHEREUM": "ETHUSDm",
    "LTCUSD": "LTCUSDm", "LTC": "LTCUSDm", "LITECOIN": "LTCUSDm",
    "XRPUSD": "XRPUSDm", "XRP": "XRPUSDm", "RIPPLE": "XRPUSDm",

    # === MAJOR FOREX PAIRS ===
    "EURUSD": "EURUSDm", "GBPUSD": "GBPUSDm", "USDJPY": "USDJPYm",
    "USDCHF": "USDCHFm", "AUDUSD": "AUDUSDm", "USDCAD": "USDCADm",
    "NZDUSD": "NZDUSDm",

    # === CROSS FOREX PAIRS ===
    "EURJPY": "EURJPYm", "GBPJPY": "GBPJPYm", "EURGBP": "EURGBPm",
    "AUDJPY": "AUDJPYm", "GBPCHF": "GBPCHFm", "EURCHF": "EURCHFm",
    "EURAUD": "EURAUDm", "GBPAUD": "GBPAUDm", "AUDCAD": "AUDCADm",
    "CADJPY": "CADJPYm", "CHFJPY": "CHFJPYm", "NZDJPY": "NZDJPYm",
    "GBPCAD": "GBPCADm", "EURNZD": "EURNZDm", "EURCAD": "EURCADm",
    "AUDNZD": "AUDNZDm", "AUDCHF": "AUDCHFm", "CADCHF": "CADCHFm",
    "NZDCAD": "NZDCADm", "NZDCHF": "NZDCHFm", "GBPNZD": "GBPNZDm",

    # === US INDICES ===
    "US30": "US30m", "DJ30": "US30m", "DOW": "US30m", "DOWJONES": "US30m", "DOWINDUSTRIAL": "US30m",
    "US500": "US500m", "SP500": "US500m", "SPX": "US500m", "SPX500": "US500m", "S&P500": "US500m", "SANDP": "US500m",
    "USTEC": "USTECm", "NAS100": "USTECm", "NASDAQ": "USTECm", "NASDAQ100": "USTECm", "NSDQ": "USTECm", "USTECH100": "USTECm", "TECH100": "USTECm",
    "US2000": "US2000m", "RUSSELL2000": "US2000m", "RUSSELL": "US2000m",

    # === EUROPEAN INDICES ===
    "DE30": "DE30m", "DAX": "DE30m", "DAX30": "DE30m", "GERMANY30": "DE30m", "GERMAN30": "DE30m",
    # FIX: DAX40 -> DE40m (not "DAX40m" which doesn't exist on Exness)
    "DE40": "DE40m", "DAX40": "DE40m", "GERMANY40": "DE40m", "GERMAN40": "DE40m",
    "UK100": "UK100m", "FTSE": "UK100m", "FTSE100": "UK100m", "UK": "UK100m",
    "FR40": "FR40m", "CAC": "FR40m", "CAC40": "FR40m", "FRANCE40": "FR40m", "FRENCH40": "FR40m",
    "ES35": "ES35m", "IBEX": "ES35m", "IBEX35": "ES35m", "SPAIN35": "ES35m", "SPANISH35": "ES35m",
    "IT40": "IT40m", "FTSEMIB": "IT40m", "ITALY40": "IT40m", "ITALIAN40": "IT40m",
    "EU50": "EU50m", "EUROSTOXX": "EU50m", "EUROSTOXX50": "EU50m", "STOXX50": "EU50m",

    # === ASIAN INDICES ===
    "JP225": "JP225m", "NIKKEI": "JP225m", "NIKKEI225": "JP225m", "JAPAN225": "JP225m", "JPN225": "JP225m",
    "HK50": "HK50m", "HANGSENG": "HK50m", "HANGSENG50": "HK50m", "HONGKONG50": "HK50m", "HSI": "HK50m",
    "CN50": "CN50m", "CHINA50": "CN50m", "CHINAA50": "CN50m",
    "AU200": "AU200m", "ASX200": "AU200m", "AUSTRALIA200": "AU200m", "AUSSIE200": "AU200m",
}

# Reverse lookup: "XAUUSDm" -> "XAUUSD" (for display)
_MT5_TO_TICKER = {}
for _k, _v in SYMBOL_MAP.items():
    if _v not in _MT5_TO_TICKER:
        _MT5_TO_TICKER[_v] = _k

# ── JSON Price Data (for Codespaces/Linux where MT5 doesn't work) ────────
_json_prices = {}


def load_json_prices():
    """Load pre-generated prices from mt5_prices.json (for cloud deployment)"""
    global _json_prices
    json_file = "mt5_prices.json"

    if not os.path.exists(json_file):
        return False

    try:
        with open(json_file, 'r') as f:
            data = json.load(f)

        print(f"📦 Loading prices from {json_file}")
        print(f"   Generated: {data.get('generated_at', 'unknown')}")

        # Build cache from JSON data
        for price_entry in data.get('prices', []):
            symbol = price_entry['symbol']
            timeframe = price_entry['timeframe']
            bars = price_entry['bars']

            # Only load D1 timeframe (daily) data
            if timeframe != 'D1':
                continue

            # Convert to pandas DataFrame (same format as MT5)
            df_data = []
            for bar in bars:
                df_data.append({
                    'time': pd.to_datetime(bar['time']),
                    'open': bar['open'],
                    'high': bar['high'],
                    'low': bar['low'],
                    'close': bar['close']
                })

            df = pd.DataFrame(df_data)
            df['day_of_week'] = df['time'].dt.dayofweek

            # Calculate answer key (same logic as _fetch_mt5_symbol)
            period_low = df['low'].min()
            period_high = df['high'].max()
            latest_close = df['close'].iloc[-1]

            weekdays = df[df['day_of_week'] <= 4]
            this_week = weekdays.tail(5) if len(weekdays) >= 5 else weekdays
            last_week = weekdays.iloc[-10:-5] if len(weekdays) >= 10 else pd.DataFrame()

            this_week_low = this_week['low'].min() if len(this_week) > 0 else period_low
            this_week_high = this_week['high'].max() if len(this_week) > 0 else period_high
            last_week_low = last_week['low'].min() if len(last_week) > 0 else period_low
            last_week_high = last_week['high'].max() if len(last_week) > 0 else period_high

            # Store formatted data
            mt5_symbol = symbol + "m" if not symbol.endswith("m") else symbol
            formatted_data = (
                f"[{mt5_symbol}] From JSON file:\n"
                f"\n>>> ANSWER KEY <<<\n"
                f"Entire Period Lowest: {period_low}\n"
                f"Entire Period Highest: {period_high}\n"
                f"Latest Close: {latest_close}\n"
                f"This Week (Mon-Fri) Lowest: {this_week_low}\n"
                f"This Week (Mon-Fri) Highest: {this_week_high}\n"
                f"Last Week (Mon-Fri) Lowest: {last_week_low}\n"
                f"Last Week (Mon-Fri) Highest: {last_week_high}"
            )

            _json_prices[mt5_symbol] = formatted_data

        print(f"   ✅ Loaded {len(_json_prices)} symbols from JSON")
        return True

    except Exception as e:
        print(f"   ❌ Failed to load JSON: {e}")
        return False


def ensure_mt5(force_retry: bool = False) -> bool:
    """Returns True if MT5 is ready. If force_retry, resets cached state."""
    global _mt5_initialized

    if not MT5_AVAILABLE:
        return False

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
    df['day_of_week'] = df['time'].dt.dayofweek  # Monday=0, Friday=4

    price_records = [
        f"{row['time'].strftime('%Y-%m-%d')} | Open: {row['open']} | Low: {row['low']} | High: {row['high']} | Close: {row['close']}"
        for _, row in df.iterrows()
    ]
    period_low = df['low'].min()
    period_high = df['high'].max()
    latest_close = df['close'].iloc[-1]

    # Trading weeks (Monday=0 to Friday=4 only)
    weekdays = df[df['day_of_week'] <= 4]
    this_week = weekdays.tail(5) if len(weekdays) >= 5 else weekdays
    last_week = weekdays.iloc[-10:-5] if len(weekdays) >= 10 else pd.DataFrame()

    this_week_low = this_week['low'].min() if len(this_week) > 0 else period_low
    this_week_high = this_week['high'].max() if len(this_week) > 0 else period_high

    last_week_low = last_week['low'].min() if len(last_week) > 0 else period_low
    last_week_high = last_week['high'].max() if len(last_week) > 0 else period_high

    return (
        f"[{mt5_symbol}] Last 14 daily candles:\n" +
        "\n".join(price_records) +
        f"\n\n>>> ANSWER KEY <<<\n"
        f"Entire Period Lowest: {period_low}\n"
        f"Entire Period Highest: {period_high}\n"
        f"Latest Close: {latest_close}\n"
        f"This Week (Mon-Fri) Lowest: {this_week_low}\n"
        f"This Week (Mon-Fri) Highest: {this_week_high}\n"
        f"Last Week (Mon-Fri) Lowest: {last_week_low}\n"
        f"Last Week (Mon-Fri) Highest: {last_week_high}"
    )


def get_market_data(ticker_symbol: str) -> str | None:
    """Fetch daily candles for a ticker. Uses cache, auto-retries MT5 on failure."""
    try:
        clean = ticker_symbol.strip().upper().replace("/", "").replace("=", "").replace("-", "").replace(" ", "")
        mt5_symbol = SYMBOL_MAP.get(clean, clean if clean.endswith("M") else clean + "m")

        # Check memory cache first
        cached = _symbol_cache.get(mt5_symbol)
        if cached and (time.time() - cached[0]) < _CACHE_TTL:
            return cached[1]

        # Try MT5 first (if available)
        if MT5_AVAILABLE:
            if not ensure_mt5():
                if not ensure_mt5(force_retry=True):
                    print(f"⚠️ MT5 unavailable, checking JSON fallback...")
            else:
                data = _fetch_mt5_symbol(mt5_symbol)
                if data:
                    _symbol_cache[mt5_symbol] = (time.time(), data)
                    return data
                else:
                    print(f"⚠️ Symbol '{mt5_symbol}' not in Market Watch.")

        # Try JSON fallback
        if mt5_symbol in _json_prices:
            print(f"📦 Using JSON data for {mt5_symbol}")
            data = _json_prices[mt5_symbol]
            _symbol_cache[mt5_symbol] = (time.time(), data)
            return data

        print(f"❌ No data available for {mt5_symbol} (not in MT5 or JSON)")

    except Exception as e:
        print(f"❌ Error fetching {ticker_symbol}: {e}")
    return None


def _pre_warm_cache():
    """Pre-fetch popular symbols at startup so first requests hit cache."""
    if not ensure_mt5():
        return
    for sym in ["XAUUSDm", "GBPJPYm", "EURUSDm", "BTCUSDm", "GBPUSDm", "USDJPYm",
                 "EURJPYm", "AUDUSDm", "USDCADm", "USDCHFm",
                 "US30m", "US500m", "USTECm", "GBPCHFm", "NZDUSDm",
                 "DE40m", "UK100m", "FR40m", "XAGUSDm"]:
        data = _fetch_mt5_symbol(sym)
        if data:
            _symbol_cache[sym] = (time.time(), data)
            print(f"  ✅ Cached {sym}")


def _resize_image(img: Image.Image, max_side: int = 768) -> Image.Image:
    """Downsample large images so Gemini upload is faster."""
    w, h = img.size
    if max(w, h) <= max_side:
        return img
    ratio = max_side / max(w, h)
    return img.resize((int(w * ratio), int(h * ratio)), Image.LANCZOS)


def _clean_answer(raw: str) -> str:
    """Strip markdown formatting and filler from Gemini response."""
    text = raw.strip()
    text = re.sub(r'\*+', '', text)
    text = re.sub(r'_+', '', text)
    for filler in ["The answer is ", "Answer: ", "answer: ", "Result: "]:
        if text.lower().startswith(filler.lower()):
            text = text[len(filler):]
    return text.strip()


def _extract_ticker_from_text(text: str) -> str | None:
    """Try to find a known ticker in OCR/Gemini text using word-boundary matching."""
    clean = text.upper()
    for ch in "/&. ,'\"#()":
        clean = clean.replace(ch, "")

    # Try exact known tickers first (longest first to match NASDAQ100 before NAS100)
    known = sorted(SYMBOL_MAP.keys(), key=len, reverse=True)
    for ticker in known:
        # Use word-boundary-like check: ticker must not be part of a longer word
        # that would cause a false match
        pattern = r'(?<![A-Z0-9])' + re.escape(ticker) + r'(?![A-Z0-9])'
        if re.search(pattern, clean):
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


# ═════════════════════════════════════════════════════════════════════════
# OCR PIPELINE  (robust: grayscale → threshold → multi-PSM → word-boundary)
# ═════════════════════════════════════════════════════════════════════════

def _preprocess_for_ocr(img: Image.Image) -> Image.Image:
    """Grayscale → sharpen → binary threshold for cleaner OCR."""
    img = img.convert('L')  # grayscale
    img = img.filter(ImageFilter.SHARPEN)
    # Binary threshold: pixels > 140 become white, else black
    img = img.point(lambda x: 255 if x > 140 else 0, '1')
    return img.convert('L')  # back to 8-bit for Tesseract


def _ocr_extract(img: Image.Image) -> str:
    """Run Tesseract with multiple PSM modes and merge results."""
    # PSM 6 = uniform block of text (best for quiz cards)
    # PSM 11 = sparse text (catches scattered words)
    # PSM 3 = fully automatic (fallback)
    results = []
    for psm in [6, 11, 3]:
        try:
            text = pytesseract.image_to_string(img, config=f'--psm {psm}').strip()
            if text:
                results.append(text)
        except Exception:
            continue
    # Merge: take the longest result (most complete), but search all for tickers
    return "\n---\n".join(results)


def _find_ticker_in_ocr(ocr_text: str) -> str | None:
    """Word-boundary ticker search across OCR text."""
    # Normalize
    normalized = ocr_text.upper()
    for ch in "/&.-,'\"#()[]{}|\\:;!?":
        normalized = normalized.replace(ch, " ")

    # Split into words for exact matching
    words = normalized.split()

    # Try exact word match first
    known = sorted(SYMBOL_MAP.keys(), key=len, reverse=True)
    for ticker in known:
        if ticker in words:
            return ticker

    # Try substring match (for "XAUUSD:" → "XAUUSD")
    joined = "".join(words)
    for ticker in known:
        if ticker in joined:
            return ticker

    # Fallback patterns
    for w in words:
        if re.match(r'^[A-Z]{6}$', w) and w[:3] != w[3:]:
            return w  # forex pair like GBPJPY
        if re.match(r'^[A-Z]{2,4}\d{2,4}$', w):
            return w  # index like US500

    return None


def solve_question_image(photo_bytes: BytesIO) -> str:
    """Choose OCR or Gemini based on availability"""
    if OCR_AVAILABLE:
        return solve_question_with_ocr(photo_bytes)
    else:
        return solve_question_with_gemini(photo_bytes)


def solve_question_with_ocr(photo_bytes: BytesIO) -> str:
    """OCR-based solver — ~0.2s total, 10x faster than Gemini."""
    try:
        t0 = time.time()

        photo_bytes.seek(0)
        img = Image.open(photo_bytes)
        img_ocr = _resize_image(img, max_side=1024)

        print(f"⏱️  Image prep: {time.time()-t0:.2f}s")

        # Preprocess for better OCR
        img_processed = _preprocess_for_ocr(img_ocr)

        # Extract text using multi-PSM OCR
        t_ocr = time.time()
        raw_text = _ocr_extract(img_processed)
        print(f"⏱️  OCR extract: {time.time()-t_ocr:.2f}s")
        # Log the FULL raw OCR text for debugging
        logger.info(f"📝 Raw OCR text:\n{raw_text}")

        # Also try OCR on the original (non-thresholded) grayscale
        # in case thresholding destroyed useful info
        img_gray = img_ocr.convert('L')
        raw_text_gray = pytesseract.image_to_string(img_gray, config='--psm 6').strip()
        if raw_text_gray:
            raw_text = raw_text + "\n---\n" + raw_text_gray

        # Parse ticker from text
        ticker = _find_ticker_in_ocr(raw_text)

        if not ticker:
            print("⚠️ No ticker found in OCR text — skipping")
            return None

        print(f"🎯 Ticker found: {ticker}")

        # Determine question type from text
        question_type = None
        text_normalized = " ".join(raw_text.lower().split())

        if ("this week" in text_normalized or "current week" in text_normalized or "thisweek" in text_normalized):
            if ("highest" in text_normalized or "high" in text_normalized or "maximum" in text_normalized):
                question_type = "THIS_WEEK_HIGH"
            elif ("lowest" in text_normalized or "low" in text_normalized or "minimum" in text_normalized):
                question_type = "THIS_WEEK_LOW"
        elif ("last week" in text_normalized or "previous week" in text_normalized or "lastweek" in text_normalized):
            if ("highest" in text_normalized or "high" in text_normalized or "maximum" in text_normalized):
                question_type = "LAST_WEEK_HIGH"
            elif ("lowest" in text_normalized or "low" in text_normalized or "minimum" in text_normalized):
                question_type = "LAST_WEEK_LOW"
        elif ("close" in text_normalized or "closing" in text_normalized):
            question_type = "LATEST_CLOSE"

        # NEW: if "high" or "low" appear without week qualifier, guess "this week"
        if not question_type:
            if ("highest" in text_normalized or "high" in text_normalized):
                question_type = "THIS_WEEK_HIGH"
                print("⚠️ No week qualifier — defaulting to THIS_WEEK_HIGH")
            elif ("lowest" in text_normalized or "low" in text_normalized):
                question_type = "THIS_WEEK_LOW"
                print("⚠️ No week qualifier — defaulting to THIS_WEEK_LOW")

        if not question_type:
            print("⚠️ Question type unclear — skipping")
            return None

        print(f"❓ Question type: {question_type}")

        # Fetch data
        t_fetch = time.time()
        data = get_market_data(ticker)
        if not data:
            return None
        print(f"⏱️  MT5 fetch: {time.time()-t_fetch:.2f}s")

        # Parse answer from data
        lines = data.split('\n')
        answer = None

        for line in lines:
            line = line.strip()
            if question_type == "THIS_WEEK_LOW" and "This Week" in line and "Lowest" in line:
                answer = line.split(':')[-1].strip()
            elif question_type == "THIS_WEEK_HIGH" and "This Week" in line and "Highest" in line:
                answer = line.split(':')[-1].strip()
            elif question_type == "LAST_WEEK_LOW" and "Last Week" in line and "Lowest" in line:
                answer = line.split(':')[-1].strip()
            elif question_type == "LAST_WEEK_HIGH" and "Last Week" in line and "Highest" in line:
                answer = line.split(':')[-1].strip()
            elif question_type == "LATEST_CLOSE" and "Latest Close:" in line:
                answer = line.split(':')[-1].strip()

        if answer:
            total_time = time.time() - t0
            print(f"⚡ OCR TOTAL TIME: {total_time:.2f}s | Answer: {answer}")
            return answer
        else:
            print("⚠️ Answer not found in data — skipping")
            return None

    except Exception as e:
        print(f"❌ OCR error: {e} — skipping")
        return None


def solve_question_with_gemini(photo_bytes: BytesIO) -> str:
    """Original Gemini-based solver (fallback when OCR unavailable)"""
    try:
        t0 = time.time()

        photo_bytes.seek(0)
        img = Image.open(photo_bytes)
        img = _resize_image(img)
        print(f"⏱️  Image load: {time.time()-t0:.2f}s")

        t_precompute = time.time()

        top_tickers = [
            "XAUUSD", "GBPJPY", "GBPUSD", "EURUSD", "USDJPY", "BTCUSD",
            "EURJPY", "AUDUSD", "USDCAD", "NZDUSD", "USDCHF", "GBPCHF",
            "NASDAQ", "US500", "US30", "XAGUSD"
        ]

        answer_db = []
        for ticker in top_tickers:
            data = get_market_data(ticker)
            if not data:
                continue

            this_week_low = this_week_high = last_week_low = last_week_high = None
            period_low = period_high = latest_close = None

            lines = data.split('\n')
            for line in lines:
                line = line.strip()
                if 'This Week' in line and 'Lowest' in line:
                    this_week_low = line.split(':')[-1].strip()
                elif 'This Week' in line and 'Highest' in line:
                    this_week_high = line.split(':')[-1].strip()
                elif 'Last Week' in line and 'Lowest' in line:
                    last_week_low = line.split(':')[-1].strip()
                elif 'Last Week' in line and 'Highest' in line:
                    last_week_high = line.split(':')[-1].strip()
                elif 'Entire Period Lowest:' in line:
                    period_low = line.split(':')[-1].strip()
                elif 'Entire Period Highest:' in line:
                    period_high = line.split(':')[-1].strip()
                elif 'Latest Close:' in line:
                    latest_close = line.split(':')[-1].strip()

            answer_db.append({
                'ticker': ticker,
                'this_week_low': this_week_low,
                'this_week_high': this_week_high,
                'last_week_low': last_week_low,
                'last_week_high': last_week_high,
                'period_low': period_low,
                'period_high': period_high,
                'latest_close': latest_close
            })

        print(f"📊 Pre-computed answers for {len(answer_db)} tickers")
        print(f"⏱️  Pre-compute: {time.time()-t_precompute:.2f}s")

        small_img = _resize_image(img.copy(), max_side=256)
        prompt = (
            "Extract info from this trading quiz:\n"
            "1. Which symbol? (e.g. XAUUSD, GBPJPY, NASDAQ)\n"
            "2. What's asked? Reply in format: SYMBOL|TYPE\n"
            "TYPE can be: THIS_WEEK_LOW, THIS_WEEK_HIGH, LAST_WEEK_LOW, LAST_WEEK_HIGH, PERIOD_LOW, PERIOD_HIGH, LATEST_CLOSE\n"
            "Example: GBPJPY|LAST_WEEK_LOW"
        )

        t_gemini_start = time.time()
        response = client_ai.models.generate_content(
            model='gemini-1.5-flash',
            contents=[prompt, small_img]
        )
        gemini_time = time.time() - t_gemini_start
        print(f"⏱️  Gemini API: {gemini_time:.2f}s")

        result = response.text.strip().upper()
        print(f"🔎 Gemini: {result}")

        if '|' not in result:
            print(f"⚠️ Gemini response format invalid — skipping")
            return None

        ticker_asked, question_type = result.split('|', 1)
        ticker_asked = ticker_asked.strip()
        question_type = question_type.strip()

        for entry in answer_db:
            if entry['ticker'].upper() == ticker_asked or ticker_asked in entry['ticker'].upper():
                answer_map = {
                    'THIS_WEEK_LOW': entry['this_week_low'],
                    'THIS_WEEK_HIGH': entry['this_week_high'],
                    'LAST_WEEK_LOW': entry['last_week_low'],
                    'LAST_WEEK_HIGH': entry['last_week_high'],
                    'PERIOD_LOW': entry['period_low'],
                    'PERIOD_HIGH': entry['period_high'],
                    'LATEST_CLOSE': entry['latest_close']
                }

                answer = answer_map.get(question_type, None)
                if answer:
                    total_time = time.time() - t0
                    print(f"⚡ TOTAL TIME: {total_time:.2f}s | Answer: {answer}")
                    return answer
                else:
                    print(f"⚠️ Question type '{question_type}' not recognized — skipping")
                    return None

        print(f"⚠️ Ticker '{ticker_asked}' not in pre-loaded list — skipping")
        return None

    except Exception as e:
        error_str = str(e)
        print(f"❌ solve_question_image error: {error_str}")

        if "PERMISSION_DENIED" in error_str or "403" in error_str:
            print("🚨 CRITICAL: Gemini API key denied!")
            return None

        if "RESOURCE_EXHAUSTED" in error_str or "429" in error_str:
            print("⏳ Rate limited — will skip this post.")
            return None

        return None


# ═════════════════════════════════════════════════════════════════════════
# CORE HANDLER: process a photo message (used by both push and poll)
# ═════════════════════════════════════════════════════════════════════════

async def _process_photo_message(client: Client, message: Message, source: str = "PUSH"):
    """Shared pipeline for handling a quiz photo. `source` is 'PUSH' or 'POLL'."""
    msg_id = message.id

    # ── Dedup: skip if already processed ──
    if msg_id in _processed_ids:
        logger.debug(f"[{source}] msg#{msg_id} already processed — skipping")
        return
    _processed_ids.add(msg_id)

    # Cap the set size
    if len(_processed_ids) > _PROCESSED_MAX:
        # Remove oldest entries (sets are unordered, but this is fine for a cap)
        excess = len(_processed_ids) - _PROCESSED_MAX
        for _ in range(excess):
            _processed_ids.pop()

    t_start = time.time()
    print(f"\n⚡ [{source}] [IMAGE from CHANNEL msg#{msg_id}] Processing...")

    answer = None
    try:
        photo_file = await client.download_media(message, in_memory=True)
        print(f"📸 Downloaded in {time.time()-t_start:.1f}s")

        # Run blocking OCR+MT5 work in a thread so Telegram stays responsive
        answer = await asyncio.to_thread(solve_question_image, photo_file)
    except Exception as e:
        print(f"❌ Photo handling error: {e}")

    if not answer:
        print("⚠️ No answer — skipped.")
        return

    # Post answer to the discussion group
    print(f"📢 Posting answer to CHAT GROUP...")
    try:
        await client.send_message(
            chat_id=TARGET_CHAT,
            text=f"{answer}"
        )
        print(f"🚀 [{source}] [POSTED to CHAT GROUP in {time.time()-t_start:.1f}s total]")
    except FloodWait as fw:
        print(f"⏳ FloodWait {fw.value}s on send — waiting...")
        await asyncio.sleep(fw.value)
        try:
            await client.send_message(chat_id=TARGET_CHAT, text=f"{answer}")
            print(f"🚀 [{source}] [POSTED after FloodWait in {time.time()-t_start:.1f}s]")
        except Exception as e2:
            print(f"❌ Failed after FloodWait: {e2}")
    except Exception as e:
        print(f"❌ Failed to post to chat: {e}")


# ═════════════════════════════════════════════════════════════════════════
# HANDLER GROUP -1: CATCH-ALL DEBUG HANDLER (runs first, all messages)
# ═════════════════════════════════════════════════════════════════════════

@app.on_message(group=-1)
async def debug_catch_all(client: Client, message: Message):
    """Log EVERY message the account receives — helps diagnose missing updates."""
    chat_id = message.chat.id
    chat_title = getattr(message.chat, 'title', None) or getattr(message.chat, 'first_name', '?')
    msg_type = "📸 PHOTO" if message.photo else "💬 TEXT" if message.text else "📎 OTHER"

    sender = "?"
    if message.sender_chat:
        sender = f"ch:{message.sender_chat.username or message.sender_chat.title}"
    elif message.from_user:
        sender = f"u:{message.from_user.username or message.from_user.first_name}"

    # Tag known chats
    tag = ""
    if chat_id == TARGET_CHANNEL:
        tag = " [★ TARGET_CHANNEL]"
    elif chat_id == TARGET_CHAT:
        tag = " [★ TARGET_CHAT]"

    logger.info(
        f"[MSG] {msg_type} #{message.id} in {chat_id} \"{chat_title}\"{tag} from={sender}"
    )

    # MUST propagate so downstream handlers fire
    message.continue_propagation()


# ═════════════════════════════════════════════════════════════════════════
# HANDLER GROUP 0: HYPE HANDLER (text from channel)
# ═════════════════════════════════════════════════════════════════════════

@app.on_message(filters.chat(TARGET_CHANNEL) & filters.text, group=0)
async def hype_quiz_announcements(client: Client, message: Message):
    """Detect quiz announcements and post hype in chat group."""
    import random

    text = message.text if message.text else ""

    ready_keywords = [
        "20$", "ዶላር", "ጥያቄ", "ደቂቃ", "ተዘጋጁ", "ይቀርባል",
        "ready", "starts", "starting", "quiz time"
    ]

    is_announcement = any(keyword in text for keyword in ready_keywords)
    if "20$" in text and "ዶላር" in text:
        is_announcement = True

    if is_announcement:
        print(f"\n🎉 QUIZ ANNOUNCEMENT DETECTED!")
        print(f"📝 Text: {text[:80]}...")

        hype_messages = [
            "Let's gooo! 🔥",
            "LET'S GO! 💪",
            "Ready! Let's goooo! 🚀",
            "Let's go! Time to win! 🏆",
            "LETS GOOOOO! 🔥🔥🔥",
            "ተዘጋጅቻለሁ! 🔥",
        ]

        wait_time = random.uniform(2, 4)
        print(f"⏳ Waiting {wait_time:.1f}s before posting hype...")
        await asyncio.sleep(wait_time)

        hype = random.choice(hype_messages)
        try:
            await client.send_message(TARGET_CHAT, hype)
            print(f"✅ Posted hype: {hype}\n")
        except Exception as e:
            print(f"❌ Error posting hype: {e}")

    message.continue_propagation()


# ═════════════════════════════════════════════════════════════════════════
# HANDLER GROUP 1: PHOTO HANDLER (push path — photo from TARGET_CHANNEL)
# ═════════════════════════════════════════════════════════════════════════

@app.on_message(filters.chat(TARGET_CHANNEL) & filters.photo, group=1)
async def handle_channel_photo(client: Client, message: Message):
    """Push handler: fires when Telegram delivers a photo from the channel."""
    await _process_photo_message(client, message, source="PUSH")


# Also handle photos that appear in the CHAT GROUP as linked-channel forwards
@app.on_message(filters.chat(TARGET_CHAT) & filters.photo, group=1)
async def handle_chat_photo(client: Client, message: Message):
    """Handle photos in the discussion group (linked channel auto-forwards)."""
    is_from_official = False

    if message.forward_from_chat and message.forward_from_chat.id == TARGET_CHANNEL:
        is_from_official = True
    elif message.sender_chat and message.sender_chat.id == TARGET_CHANNEL:
        is_from_official = True

    if not is_from_official:
        return  # ignore random user photos in group

    await _process_photo_message(client, message, source="PUSH-CHAT")


# ═════════════════════════════════════════════════════════════════════════
# POLLING FALLBACK — catches updates that push missed
# ═════════════════════════════════════════════════════════════════════════

async def _poll_channel(client: Client):
    """
    Every ~1s, fetch the latest message from TARGET_CHANNEL.
    If it's a photo we haven't processed, run the pipeline.
    This is the safety net for when Telegram doesn't push updates
    to a passive member account.
    """
    logger.info("🔄 Polling fallback started (checking every 1s)")
    last_seen_id = 0

    # Seed last_seen_id with the current latest message
    try:
        async for msg in client.get_chat_history(TARGET_CHANNEL, limit=1):
            last_seen_id = msg.id
            logger.info(f"🔄 Poll seeded: last_seen_id = {last_seen_id}")
    except Exception as e:
        logger.warning(f"🔄 Poll seed failed: {e}")

    backoff = 1.0  # normal interval
    while True:
        try:
            async for msg in client.get_chat_history(TARGET_CHANNEL, limit=3):
                if msg.id <= last_seen_id:
                    break
                if msg.id > last_seen_id:
                    last_seen_id = msg.id

                if msg.photo:
                    if msg.id not in _processed_ids:
                        logger.info(f"🔄 [POLL] New photo detected: msg#{msg.id}")
                        await _process_photo_message(client, msg, source="POLL")

            backoff = 1.0  # reset on success

        except FloodWait as fw:
            wait = fw.value + 1
            logger.warning(f"🔄 Poll FloodWait: sleeping {wait}s")
            backoff = min(backoff * 2, 30)  # exponential backoff
            await asyncio.sleep(wait)
            continue
        except (ConnectionError, OSError) as e:
            logger.warning(f"🔄 Poll connection error: {e} — retrying in {backoff}s")
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, 30)
            continue
        except Exception as e:
            logger.error(f"🔄 Poll unexpected error: {e}")
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, 30)
            continue

        await asyncio.sleep(backoff)


# ═════════════════════════════════════════════════════════════════════════
# KEEP-ALIVE: mark account "online" so Telegram keeps pushing updates
# ═════════════════════════════════════════════════════════════════════════

async def _keep_online(client: Client):
    """
    Periodically call get_me() / invoke UpdateStatus to keep the
    account marked as 'online'. Telegram may stop pushing channel
    updates to accounts it considers idle/offline.
    """
    from pyrogram.raw.functions.account import UpdateStatus

    logger.info("🟢 Keep-online task started (every 4 min)")
    while True:
        try:
            # Mark as "online" (not_offline=True means we ARE online)
            await client.invoke(UpdateStatus(offline=False))
            logger.debug("🟢 Marked online")
        except FloodWait as fw:
            await asyncio.sleep(fw.value)
        except Exception as e:
            logger.warning(f"🟢 keep_online error: {e}")
        await asyncio.sleep(240)  # every 4 minutes


# ═════════════════════════════════════════════════════════════════════════
# STARTUP: resolve channels, load dialogs, validate membership
# ═════════════════════════════════════════════════════════════════════════

async def _startup_checks(client: Client):
    """
    Run at startup after client.start():
    1. Load dialogs (forces Pyrogram to cache peers → enables push updates)
    2. Resolve TARGET_CHANNEL and TARGET_CHAT
    3. Verify membership
    4. Print diagnostics
    """
    print("\n" + "=" * 60)
    print("🔍 STARTUP CHECKS")
    print("=" * 60)

    # ── Step 1: Load dialogs (CRITICAL for push updates) ──────────────
    # Pyrogram can only dispatch updates for chats it has in its internal
    # peer database. Loading dialogs populates this database. Without this,
    # a passive member's channel posts may never trigger handlers.
    print("\n📂 Loading dialogs to populate peer cache...")
    dialog_count = 0
    target_channel_found = False
    target_chat_found = False
    try:
        async for dialog in client.get_dialogs():
            dialog_count += 1
            if dialog.chat.id == TARGET_CHANNEL:
                target_channel_found = True
                print(f"   ✅ Found TARGET_CHANNEL: {dialog.chat.title} ({dialog.chat.id})")
            if dialog.chat.id == TARGET_CHAT:
                target_chat_found = True
                print(f"   ✅ Found TARGET_CHAT: {dialog.chat.title} ({dialog.chat.id})")
        print(f"   📂 Loaded {dialog_count} dialogs total")
    except Exception as e:
        print(f"   ❌ Error loading dialogs: {e}")

    # ── Step 2: Resolve channels directly if not found in dialogs ─────
    if not target_channel_found:
        print(f"\n⚠️ TARGET_CHANNEL ({TARGET_CHANNEL}) NOT in dialogs!")
        print(f"   Trying to resolve directly...")
        try:
            ch = await client.get_chat(TARGET_CHANNEL)
            print(f"   ✅ Resolved: {ch.title} (type={ch.type})")
            # Try to join if not a member
            try:
                await client.join_chat(ch.username or TARGET_CHANNEL)
                print(f"   ✅ Joined channel!")
            except Exception:
                pass  # already a member or can't join
        except ChannelPrivate:
            print(f"   ❌ FATAL: Channel is private and account is NOT a member!")
            print(f"   → Your sister must join this channel from the Telegram app first.")
            sys.exit(1)
        except PeerIdInvalid:
            print(f"   ❌ FATAL: Peer ID invalid — the channel ID may be wrong.")
            print(f"   → Run find_channels.py to get the correct ID.")
            sys.exit(1)
        except Exception as e:
            print(f"   ❌ Cannot resolve channel: {e}")
            print(f"   → The account may not be a member. Join from Telegram app.")
            sys.exit(1)

    if not target_chat_found:
        print(f"\n⚠️ TARGET_CHAT ({TARGET_CHAT}) NOT in dialogs!")
        try:
            ch = await client.get_chat(TARGET_CHAT)
            print(f"   ✅ Resolved: {ch.title} (type={ch.type})")
            try:
                await client.join_chat(ch.username or TARGET_CHAT)
                print(f"   ✅ Joined chat group!")
            except Exception:
                pass
        except Exception as e:
            print(f"   ❌ Cannot resolve chat group: {e}")
            print(f"   → The account may not be a member. Join from Telegram app.")
            sys.exit(1)

    # ── Step 3: Verify we can read the channel ────────────────────────
    print(f"\n📖 Verifying read access to channel...")
    try:
        count = 0
        async for msg in client.get_chat_history(TARGET_CHANNEL, limit=3):
            count += 1
            msg_type = "PHOTO" if msg.photo else "TEXT" if msg.text else "OTHER"
            print(f"   #{msg.id} [{msg_type}] {(msg.text or msg.caption or '')[:60]}")
        if count == 0:
            print(f"   ⚠️ Channel appears empty")
        else:
            print(f"   ✅ Can read {count} messages")
    except Exception as e:
        print(f"   ❌ Cannot read channel history: {e}")

    # ── Step 4: Show account info ─────────────────────────────────────
    try:
        me = await client.get_me()
        print(f"\n👤 Logged in as: {me.first_name} (@{me.username or 'no-username'}) id={me.id}")
    except Exception as e:
        print(f"\n⚠️ Could not get account info: {e}")

    print("\n" + "=" * 60)
    print("✅ STARTUP CHECKS COMPLETE — bot is live!")
    print(f"   Listening for photos on channel {TARGET_CHANNEL}")
    print(f"   Posting answers to group {TARGET_CHAT}")
    print(f"   Polling fallback: every ~1s")
    print(f"   Keep-online: every 4 min")
    print("=" * 60 + "\n")


# ═════════════════════════════════════════════════════════════════════════
# MAIN
# ═════════════════════════════════════════════════════════════════════════

async def main():
    # Load JSON prices
    json_loaded = load_json_prices()

    # Initialize MT5 (Windows only)
    if MT5_AVAILABLE:
        print("🤖 Initializing MT5 connection...")
        if mt5.initialize():
            global _mt5_initialized
            _mt5_initialized = True
            print("✅ MT5 Connected!")
            print("📊 Pre-warming cache...")
            _pre_warm_cache()
        else:
            print(f"⚠️ MT5 Warning: {mt5.last_error()}")
            if not json_loaded:
                print("❌ CRITICAL: No MT5 and no JSON data available!")
                sys.exit(1)
    else:
        if not json_loaded:
            print("❌ CRITICAL: No JSON price data found!")
            sys.exit(1)
        print("✅ Using JSON price data for quiz answers")

    # ── Start Pyrogram ────────────────────────────────────────────────
    await app.start()

    # ── Run startup checks (load dialogs, verify membership) ─────────
    await _startup_checks(app)

    # ── Launch background tasks ──────────────────────────────────────
    poll_task = asyncio.create_task(_poll_channel(app))
    online_task = asyncio.create_task(_keep_online(app))

    print("🤖 Bot is running. Press Ctrl+C to stop.\n")

    # Keep running until interrupted
    try:
        # idle() keeps the event loop running and handles Ctrl+C
        await asyncio.Event().wait()
    except (KeyboardInterrupt, SystemExit):
        print("\n🛑 Shutting down...")
    finally:
        poll_task.cancel()
        online_task.cancel()
        await app.stop()
        if MT5_AVAILABLE and _mt5_initialized:
            mt5.shutdown()
        print("👋 Bot stopped.")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n👋 Bye!")
