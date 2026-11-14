"""
Quiz answer userbot (FAST edition)
----------------------------------
* Logs EVERY post of the quiz channel (text, photo, video...).
* Answers ONLY image posts, as a REPLY to that post's copy in the linked discussion group.
* OCR passes run in PARALLEL, and Gemini RACES the OCR (first valid answer wins).
* The post's copy in the group is found by PUSH (instant) with API polling as backup.
* NEVER guesses: if candle data does not cover the week asked, it refuses and says why.
* Prints per-stage timings so you can see exactly where time goes.

Test without Telegram:   python bot_fast.py --test path/to/quiz.png

.env keys
  required : TELEGRAM_API_ID, TELEGRAM_API_HASH, TARGET_CHANNEL, TARGET_CHAT
  optional : GEMINI_API_KEY, GEMINI_MODEL=gemini-2.5-flash
             GEMINI_MODE=race|fallback|off     (default race; legacy USE_GEMINI_FALLBACK=0 -> off)
             GEMINI_TIMEOUT=6
             OCR_WORKERS=<n>                   (default: cpu count, 2..4)
             POLL_INTERVAL=1.0                 (safety-net poll, seconds)
             DISCUSSION_GRACE=3.0              (max extra wait for the post's copy once answer is ready)
             REPLY_FALLBACK_TO_PLAIN=1         (post plain message if the copy is not found)
             PRE_SEND_GUARD=0                  (1 = slower, checks history for duplicates before sending)
             HYPE_ENABLED=0, SHOW_GROUP_MESSAGES=0, LOG_LEVEL=INFO
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import random
import re
import socket
import sys
import threading
import time
import warnings
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor
from io import BytesIO

from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(
    level=getattr(logging, os.getenv("LOG_LEVEL", "INFO").upper(), logging.INFO),
    format="%(asctime)s.%(msecs)03d [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("bot")
logging.getLogger("pyrogram").setLevel(logging.WARNING)

if sys.stdout.encoding != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8")

# Tesseract spawns its own threads; with several passes in parallel that causes oversubscription.
os.environ.setdefault("OMP_THREAD_LIMIT", "1")

# ── Speed-ups that are optional but free ─────────────────────────────────
try:
    import tgcrypto  # noqa: F401

    log.info("⚡ tgcrypto: active (fast encryption)")
except ImportError:
    log.warning("⚠️ tgcrypto missing -> run `pip install tgcrypto` (noticeably faster downloads/sends)")

if os.name != "nt":
    try:
        import uvloop

        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            uvloop.install()
        log.info("⚡ uvloop: active")
    except ImportError:
        log.info("ℹ️ uvloop not installed (optional, Linux only): pip install uvloop")

import pandas as pd
from PIL import Image, ImageFilter, ImageOps, ImageStat
from pyrogram import Client, filters, idle
from pyrogram.errors import ChannelPrivate, FloodWait, PeerIdInvalid
from pyrogram.types import Message

try:
    import google.genai as genai
except ImportError:
    genai = None

# ── MT5 (Windows only) ───────────────────────────────────────────────────
try:
    import MetaTrader5 as mt5

    MT5_AVAILABLE = True
    log.info("✅ MT5: available (Windows)")
except ImportError:
    mt5 = None
    MT5_AVAILABLE = False
    log.info("⚠️ MT5: not available (using mt5_prices.json)")

# ── OCR ──────────────────────────────────────────────────────────────────
OCR_AVAILABLE = False
try:
    import pytesseract

    if os.name == "nt":
        for _p in (
            r"C:\Program Files\Tesseract-OCR\tesseract.exe",
            r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe",
            r"C:\Tesseract-OCR\tesseract.exe",
        ):
            if os.path.exists(_p):
                pytesseract.pytesseract.tesseract_cmd = _p
                break
    pytesseract.get_tesseract_version()
    OCR_AVAILABLE = True
    log.info("✅ OCR: enabled")
except Exception as _e:
    log.warning(f"⚠️ OCR: disabled ({_e})")


# ═════════════════════════════════════════════════════════════════════════
# CONFIG
# ═════════════════════════════════════════════════════════════════════════
def _env_int(name: str) -> int:
    v = os.getenv(name)
    if not v:
        sys.exit(f"❌ Missing {name} in .env")
    return int(v.strip())


def _env_flag(name: str, default: str = "0") -> bool:
    return os.getenv(name, default).strip() == "1"


API_ID = _env_int("TELEGRAM_API_ID")
API_HASH = os.getenv("TELEGRAM_API_HASH")
TARGET_CHANNEL = _env_int("TARGET_CHANNEL")  # quiz channel (we READ it)
TARGET_CHAT = _env_int("TARGET_CHAT")        # linked discussion group (we ANSWER there)

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")
GEMINI_MODE = os.getenv("GEMINI_MODE", "race" if _env_flag("USE_GEMINI_FALLBACK", "1") else "off").lower()
GEMINI_TIMEOUT = float(os.getenv("GEMINI_TIMEOUT", "6"))
client_ai = genai.Client(api_key=GEMINI_API_KEY) if (genai and GEMINI_API_KEY) else None
if not client_ai:
    GEMINI_MODE = "off"

HYPE_ENABLED = _env_flag("HYPE_ENABLED")
SHOW_GROUP_MESSAGES = _env_flag("SHOW_GROUP_MESSAGES")
REPLY_FALLBACK_TO_PLAIN = _env_flag("REPLY_FALLBACK_TO_PLAIN", "1")
PRE_SEND_GUARD = _env_flag("PRE_SEND_GUARD")

MAX_POST_AGE = 180          # ignore image posts older than this (seconds)
POLL_INTERVAL = float(os.getenv("POLL_INTERVAL", "1.0"))
DISCUSSION_GRACE = float(os.getenv("DISCUSSION_GRACE", "3.0"))
DISCUSSION_MAX_WAIT = 20.0  # absolute cap for looking up the post's copy
MT5_CACHE_TTL = 5
SESSION_WINDOW = 1800
LOCK_PORT = 47831

OCR_MIN_W, OCR_MAX_W = 1000, 1400   # smaller image = faster Tesseract; raise OCR_MAX_W if accuracy drops
OCR_WORKERS = int(os.getenv("OCR_WORKERS", str(max(2, min(4, os.cpu_count() or 2)))))
OCR_POOL = ThreadPoolExecutor(max_workers=OCR_WORKERS, thread_name_prefix="ocr")
OCR_PASSES = [(False, 6), (True, 6), (False, 11), (True, 3)]  # (binarize, psm) — first has priority

app = Client("fast_image_userbot", api_id=API_ID, api_hash=API_HASH, sleep_threshold=20)

# ── State ────────────────────────────────────────────────────────────────
_mt5_initialized = False
_data_lock = threading.Lock()  # MT5 API is not guaranteed thread-safe
_symbol_cache: dict[str, tuple[float, dict]] = {}
_json_frames: dict[str, tuple[pd.DataFrame, int]] = {}
_json_meta: dict = {"generated_at": None, "mtime": None}

_SEEN_MAX = 1000
_seen: "OrderedDict[tuple, float]" = OrderedDict()
_bg_tasks: set[asyncio.Task] = set()


def _claim(key: tuple) -> bool:
    """True the first time a key is seen, False afterwards."""
    if key in _seen:
        return False
    _seen[key] = time.time()
    while len(_seen) > _SEEN_MAX:
        _seen.popitem(last=False)
    return True


def _spawn(coro) -> asyncio.Task:
    """create_task that keeps a reference so the task is never garbage-collected."""
    t = asyncio.create_task(coro)
    _bg_tasks.add(t)
    t.add_done_callback(_bg_tasks.discard)
    return t


async def _cancel(task: asyncio.Future | None) -> None:
    if task and not task.done():
        task.cancel()
        try:
            await task
        except (asyncio.CancelledError, Exception):
            pass


# ═════════════════════════════════════════════════════════════════════════
# SYMBOL MAP
# ═════════════════════════════════════════════════════════════════════════
SYMBOL_MAP = {
    "GOLD": "XAUUSDm", "XAUUSD": "XAUUSDm",
    "SILVER": "XAGUSDm", "XAGUSD": "XAGUSDm",
    "USOIL": "USOILm", "OIL": "USOILm", "CRUDE": "USOILm", "WTI": "USOILm",
    "UKOIL": "UKOILm", "BRENT": "UKOILm",
    "BTCUSD": "BTCUSDm", "BTC": "BTCUSDm", "BITCOIN": "BTCUSDm",
    "ETHUSD": "ETHUSDm", "ETH": "ETHUSDm", "ETHEREUM": "ETHUSDm",
    "LTCUSD": "LTCUSDm", "LTC": "LTCUSDm", "LITECOIN": "LTCUSDm",
    "XRPUSD": "XRPUSDm", "XRP": "XRPUSDm", "RIPPLE": "XRPUSDm",
    "EURUSD": "EURUSDm", "GBPUSD": "GBPUSDm", "USDJPY": "USDJPYm",
    "USDCHF": "USDCHFm", "AUDUSD": "AUDUSDm", "USDCAD": "USDCADm",
    "NZDUSD": "NZDUSDm",
    "EURJPY": "EURJPYm", "GBPJPY": "GBPJPYm", "EURGBP": "EURGBPm",
    "AUDJPY": "AUDJPYm", "GBPCHF": "GBPCHFm", "EURCHF": "EURCHFm",
    "EURAUD": "EURAUDm", "GBPAUD": "GBPAUDm", "AUDCAD": "AUDCADm",
    "CADJPY": "CADJPYm", "CHFJPY": "CHFJPYm", "NZDJPY": "NZDJPYm",
    "GBPCAD": "GBPCADm", "EURNZD": "EURNZDm", "EURCAD": "EURCADm",
    "AUDNZD": "AUDNZDm", "AUDCHF": "AUDCHFm", "CADCHF": "CADCHFm",
    "NZDCAD": "NZDCADm", "NZDCHF": "NZDCHFm", "GBPNZD": "GBPNZDm",
    "US30": "US30m", "DJ30": "US30m", "DOW": "US30m", "DOWJONES": "US30m", "DOWINDUSTRIAL": "US30m",
    "US500": "US500m", "SP500": "US500m", "SPX": "US500m", "SPX500": "US500m", "SANDP": "US500m",
    "USTEC": "USTECm", "NAS100": "USTECm", "NASDAQ": "USTECm", "NASDAQ100": "USTECm", "NSDQ": "USTECm",
    "USTECH100": "USTECm", "TECH100": "USTECm",
    "US2000": "US2000m", "RUSSELL2000": "US2000m", "RUSSELL": "US2000m",
    "DE30": "DE30m", "DAX": "DE30m", "DAX30": "DE30m", "GERMANY30": "DE30m", "GERMAN30": "DE30m",
    "DE40": "DE40m", "DAX40": "DE40m", "GERMANY40": "DE40m", "GERMAN40": "DE40m",
    "UK100": "UK100m", "FTSE": "UK100m", "FTSE100": "UK100m",
    "FR40": "FR40m", "CAC": "FR40m", "CAC40": "FR40m", "FRANCE40": "FR40m", "FRENCH40": "FR40m",
    "ES35": "ES35m", "IBEX": "ES35m", "IBEX35": "ES35m", "SPAIN35": "ES35m", "SPANISH35": "ES35m",
    "IT40": "IT40m", "FTSEMIB": "IT40m", "ITALY40": "IT40m", "ITALIAN40": "IT40m",
    "EU50": "EU50m", "EUROSTOXX": "EU50m", "EUROSTOXX50": "EU50m", "STOXX50": "EU50m",
    "JP225": "JP225m", "NIKKEI": "JP225m", "NIKKEI225": "JP225m", "JAPAN225": "JP225m", "JPN225": "JP225m",
    "HK50": "HK50m", "HANGSENG": "HK50m", "HANGSENG50": "HK50m", "HONGKONG50": "HK50m", "HSI": "HK50m",
    "CN50": "CN50m", "CHINA50": "CN50m", "CHINAA50": "CN50m",
    "AU200": "AU200m", "ASX200": "AU200m", "AUSTRALIA200": "AU200m", "AUSSIE200": "AU200m",
}
CURRENCIES = {"USD", "EUR", "GBP", "JPY", "CHF", "AUD", "CAD", "NZD", "XAU", "XAG"}

PREWARM_SYMBOLS = [
    "XAUUSDm", "GBPJPYm", "EURUSDm", "BTCUSDm", "GBPUSDm", "USDJPYm", "EURJPYm", "AUDUSDm",
    "USDCADm", "USDCHFm", "US30m", "US500m", "USTECm", "GBPCHFm", "NZDUSDm", "DE40m",
    "UK100m", "FR40m", "XAGUSDm",
]


# ═════════════════════════════════════════════════════════════════════════
# MARKET DATA  (strict: never guesses)
# ═════════════════════════════════════════════════════════════════════════
def _infer_digits(series) -> int:
    best = 0
    for v in series:
        s = f"{float(v):.8f}".rstrip("0")
        best = max(best, len(s.split(".")[1]) if "." in s else 0)
    return min(best, 6)


def _build_keys(df: pd.DataFrame, digits: int, now: pd.Timestamp | None = None) -> dict:
    """
    'This week' = Mon-Fri of the CURRENT calendar week; 'last week' = the week before.
    A week with no candles gives None (NOT a fallback to some other period).
    """
    df = df.sort_values("time").reset_index(drop=True).copy()
    df["time"] = pd.to_datetime(df["time"])
    df["dow"] = df["time"].dt.dayofweek
    now = now if now is not None else pd.Timestamp.now()

    weekdays = df[df["dow"] <= 4]
    this_monday = (now - pd.Timedelta(days=now.dayofweek)).normalize()
    last_monday = this_monday - pd.Timedelta(days=7)

    def week_of(monday):
        end = monday + pd.Timedelta(days=5)
        return weekdays[(weekdays["time"] >= monday) & (weekdays["time"] < end)]

    this_week, last_week = week_of(this_monday), week_of(last_monday)

    def lo(x):
        return float(x["low"].min()) if len(x) else None

    def hi(x):
        return float(x["high"].max()) if len(x) else None

    return {
        "digits": digits,
        "now": now,
        "period_low": float(df["low"].min()),
        "period_high": float(df["high"].max()),
        "latest_close": float(df["close"].iloc[-1]),
        "this_week_low": lo(this_week),
        "this_week_high": hi(this_week),
        "last_week_low": lo(last_week),
        "last_week_high": hi(last_week),
        "this_count": len(this_week),
        "last_count": len(last_week),
        "this_monday": this_monday,
        "last_monday": last_monday,
        "last_candle": df["time"].iloc[-1],
        "source": "?",
    }


def _answer_from_data(data: dict, question_type: str) -> tuple[str | None, str]:
    """Returns (answer or None, explanation). Refuses when the data cannot be trusted."""
    now = data["now"]
    weekend = now.dayofweek >= 5
    tm, lm = data["this_monday"], data["last_monday"]
    info = (
        f"{question_type} | source={data['source']} | last candle {data['last_candle'].date()} | "
        f"this week {tm.date()}..{(tm + pd.Timedelta(days=4)).date()} ({data['this_count']} candles) | "
        f"last week {lm.date()}..{(lm + pd.Timedelta(days=4)).date()} ({data['last_count']} candles)"
    )

    if question_type.startswith("THIS_WEEK"):
        if data["this_count"] == 0:
            return None, f"🛑 REFUSING: no candles for the current week — data is STALE. {info}"
        if weekend and data["this_count"] < 4:
            return None, (f"🛑 REFUSING: only {data['this_count']} candles this week on a weekend — "
                          f"data incomplete. {info}")
    elif question_type.startswith("LAST_WEEK"):
        if data["last_count"] < 3:
            return None, (f"🛑 REFUSING: only {data['last_count']} candles for last week — "
                          f"data incomplete/stale. {info}")

    value = data.get(question_type.lower())
    if value is None:
        return None, f"🛑 REFUSING: no value for {question_type}. {info}"
    return f"{value:.{data['digits']}f}", info


# ── JSON fallback ────────────────────────────────────────────────────────
def load_json_prices() -> bool:
    json_file = "mt5_prices.json"
    if not os.path.exists(json_file):
        return False
    try:
        with open(json_file, "r") as f:
            data = json.load(f)

        frames: dict[str, tuple[pd.DataFrame, int]] = {}
        for entry in data.get("prices", []):
            if entry.get("timeframe") != "D1" or not entry.get("bars"):
                continue
            df = pd.DataFrame(
                [
                    {"time": pd.to_datetime(b["time"]), "open": b["open"], "high": b["high"],
                     "low": b["low"], "close": b["close"]}
                    for b in entry["bars"]
                ]
            )
            sym = entry["symbol"]
            mt5_symbol = sym if sym.endswith("m") else sym + "m"
            digits = entry.get("digits")
            if digits is None:
                digits = _infer_digits(pd.concat([df["low"], df["high"], df["close"]]))
            frames[mt5_symbol] = (df, int(digits))

        _json_frames.clear()
        _json_frames.update(frames)
        _json_meta["generated_at"] = data.get("generated_at", "unknown")
        _json_meta["mtime"] = os.path.getmtime(json_file)
        _symbol_cache.clear()
        log.info(f"📦 Loaded {json_file}: {len(frames)} symbols (generated {_json_meta['generated_at']})")
        return bool(frames)
    except Exception as e:
        log.error(f"❌ Failed to load JSON: {e}")
        return False


def _maybe_reload_json() -> None:
    """After a `git pull` the new file is picked up automatically — no restart needed."""
    try:
        m = os.path.getmtime("mt5_prices.json")
        if _json_meta["mtime"] is not None and m != _json_meta["mtime"]:
            log.info("🔁 mt5_prices.json changed — reloading")
            load_json_prices()
    except OSError:
        pass


# ── MT5 ──────────────────────────────────────────────────────────────────
def ensure_mt5(force_retry: bool = False) -> bool:
    global _mt5_initialized
    if not MT5_AVAILABLE:
        return False
    if force_retry:
        _mt5_initialized = False
    if not _mt5_initialized:
        _mt5_initialized = bool(mt5.initialize())
    return _mt5_initialized


def _fetch_mt5_symbol(mt5_symbol: str) -> dict | None:
    mt5.symbol_select(mt5_symbol, True)
    rates = mt5.copy_rates_from_pos(mt5_symbol, mt5.TIMEFRAME_D1, 0, 30)
    if rates is None or len(rates) == 0:
        return None
    df = pd.DataFrame(rates)
    df["time"] = pd.to_datetime(df["time"], unit="s")
    info = mt5.symbol_info(mt5_symbol)
    data = _build_keys(df, info.digits if info else 5)
    data["source"] = "MT5 live"
    return data


def _resolve_symbol(ticker: str) -> str:
    clean = re.sub(r"[^A-Z0-9]", "", ticker.upper())
    if clean in SYMBOL_MAP:
        return SYMBOL_MAP[clean]
    return clean[:-1] + "m" if clean.endswith("M") else clean + "m"


def get_market_data(ticker: str) -> dict | None:
    try:
        mt5_symbol = _resolve_symbol(ticker)
        with _data_lock:
            cached = _symbol_cache.get(mt5_symbol)
            if cached and (time.time() - cached[0]) < MT5_CACHE_TTL:
                return cached[1]

            data = None
            if MT5_AVAILABLE:
                if ensure_mt5() or ensure_mt5(force_retry=True):
                    data = _fetch_mt5_symbol(mt5_symbol)
                    if not data:
                        log.warning(f"⚠️ '{mt5_symbol}' not in Market Watch — trying JSON")
                else:
                    log.warning("⚠️ MT5 unavailable — trying JSON")

            if data is None and mt5_symbol in _json_frames:
                df, digits = _json_frames[mt5_symbol]
                data = _build_keys(df, digits)
                data["source"] = f"JSON generated {_json_meta['generated_at']}"

            if data is None:
                log.error(f"❌ No data for {mt5_symbol} (not in MT5 or JSON)")
                return None
            data["symbol"] = mt5_symbol
            _symbol_cache[mt5_symbol] = (time.time(), data)
            return data
    except Exception as e:
        log.error(f"❌ Error fetching {ticker}: {e}")
        return None


def _pre_warm_cache() -> None:
    if not ensure_mt5():
        return
    for sym in PREWARM_SYMBOLS:
        if mt5.symbol_select(sym, True):
            log.debug(f"  ✅ Selected {sym}")


def _lookup(ticker: str, qtype: str) -> str | None:
    data = get_market_data(ticker)
    if not data:
        return None
    answer, info = _answer_from_data(data, qtype)
    log.info(f"{'🧮' if answer else '🛑'} {data.get('symbol', ticker)} → {answer} | {info}")
    return answer


async def _lookup_async(ticker: str, qtype: str) -> str | None:
    return await asyncio.get_running_loop().run_in_executor(None, _lookup, ticker, qtype)


# ═════════════════════════════════════════════════════════════════════════
# QUESTION PARSING
# ═════════════════════════════════════════════════════════════════════════
_INDEX_RE = re.compile(r"(US|DE|UK|FR|ES|IT|EU|JP|HK|CN|AU)\d{2,4}")


def _find_ticker(text: str) -> str | None:
    tokens = re.sub(r"[^A-Z0-9]+", " ", text.upper()).split()
    for i, tok in enumerate(tokens):
        if len(tok) >= 3 and tok in SYMBOL_MAP:
            return tok
        for n in (2, 3):  # 'XAU USD', 'S&P 500'
            if i + n <= len(tokens):
                joined = "".join(tokens[i:i + n])
                if len(joined) >= 4 and joined in SYMBOL_MAP:
                    return joined
        if (re.fullmatch(r"[A-Z]{6}", tok)
                and tok[:3] in CURRENCIES and tok[3:] in CURRENCIES and tok[:3] != tok[3:]):
            return tok
        if _INDEX_RE.fullmatch(tok):
            return tok
    return None


def _parse_question_type(text: str) -> str | None:
    t = " ".join(text.lower().split())

    def pos(pattern: str) -> int | None:
        m = re.search(pattern, t)
        return m.start() if m else None

    this_pos = pos(r"\b(this|current)\s*week")
    last_pos = pos(r"\b(last|previous|past)\s*week")
    hi = pos(r"\b(highest|high|maximum|max|peak)\b")
    lo = pos(r"\b(lowest|low|minimum|min)\b")
    cl = pos(r"\b(close|closing|closed)\b")

    if hi is None and lo is None:
        return "LATEST_CLOSE" if cl is not None else None

    side = "HIGH" if (lo is None or (hi is not None and hi < lo)) else "LOW"
    week = "LAST" if (last_pos is not None and (this_pos is None or last_pos < this_pos)) else "THIS"
    return f"{week}_WEEK_{side}"


# ═════════════════════════════════════════════════════════════════════════
# SOLVERS: OCR (parallel passes) + GEMINI (async)   -> raced in solve_image()
# ═════════════════════════════════════════════════════════════════════════
def _open_image(photo: BytesIO) -> Image.Image:
    photo.seek(0)
    img = Image.open(photo)
    img.load()
    return img


def _base_prep(img: Image.Image) -> Image.Image:
    """Heavy preprocessing done ONCE and shared by every OCR pass."""
    g = img.convert("L")
    w = g.width
    if w < OCR_MIN_W or w > OCR_MAX_W:
        f = (OCR_MIN_W if w < OCR_MIN_W else OCR_MAX_W) / w
        g = g.resize((int(w * f), int(g.height * f)), Image.BICUBIC)
    g = ImageOps.autocontrast(g)
    if ImageStat.Stat(g).mean[0] < 110:  # dark card -> invert (Tesseract wants dark-on-light)
        g = ImageOps.invert(g)
    return g


def _ocr_pass(base: Image.Image, binarize: bool, psm: int) -> str:
    g = base
    if binarize:
        g = g.filter(ImageFilter.SHARPEN).point(lambda x: 255 if x > 140 else 0)
    return pytesseract.image_to_string(g, config=f"--psm {psm}").strip()


async def solve_with_ocr(img: Image.Image) -> str | None:
    loop = asyncio.get_running_loop()
    t0 = time.perf_counter()
    base = await loop.run_in_executor(OCR_POOL, _base_prep, img)
    # all passes start at once; pass #1 keeps priority, the others are only used if it fails
    futs = [loop.run_in_executor(OCR_POOL, _ocr_pass, base, b, p) for b, p in OCR_PASSES]
    texts: list[str] = []
    ticker = qtype = None
    try:
        try:
            first = await futs[0]
        except Exception as e:
            log.warning(f"OCR pass 1 failed: {e}")
            first = ""
        if first:
            texts.append(first)
            ticker, qtype = _find_ticker(first), _parse_question_type(first)

        pending = set(futs[1:])
        while pending and not (ticker and qtype):
            done, pending = await asyncio.wait(pending, return_when=asyncio.FIRST_COMPLETED)
            for f in done:
                try:
                    text = f.result()
                except Exception:
                    continue
                if not text:
                    continue
                texts.append(text)
                tk, qt = _find_ticker(text), _parse_question_type(text)
                if tk and qt:
                    ticker, qtype = tk, qt
                    break
    finally:
        for f in futs:  # not-yet-started passes are dropped, running ones finish harmlessly
            f.cancel()

    if not (ticker and qtype) and texts:
        merged = "\n".join(texts)
        ticker = ticker or _find_ticker(merged)
        qtype = qtype or _parse_question_type(merged)

    log.debug("📝 OCR text:\n" + ("\n".join(texts)[:600] or "(nothing read)"))
    log.info(f"⏱️  OCR {time.perf_counter() - t0:.2f}s | ticker={ticker} | type={qtype}")
    if not ticker or not qtype:
        return None
    return await _lookup_async(ticker, qtype)


GEMINI_TYPES = {"THIS_WEEK_LOW", "THIS_WEEK_HIGH", "LAST_WEEK_LOW", "LAST_WEEK_HIGH",
                "PERIOD_LOW", "PERIOD_HIGH", "LATEST_CLOSE"}
GEMINI_PROMPT = (
    "This is a trading quiz image. Reply ONLY in the format SYMBOL|TYPE.\n"
    "SYMBOL: the instrument ticker (e.g. XAUUSD, GBPJPY, NASDAQ).\n"
    "TYPE: one of THIS_WEEK_LOW, THIS_WEEK_HIGH, LAST_WEEK_LOW, LAST_WEEK_HIGH, "
    "PERIOD_LOW, PERIOD_HIGH, LATEST_CLOSE.\nExample: GBPJPY|LAST_WEEK_LOW"
)


def _gemini_config():
    """Fast, deterministic, no 'thinking' — we only need two tokens back."""
    try:
        from google.genai import types

        return types.GenerateContentConfig(
            temperature=0,
            max_output_tokens=24,
            thinking_config=types.ThinkingConfig(thinking_budget=0),
        )
    except Exception:
        return None


_GEMINI_CFG = _gemini_config() if client_ai else None


def _thumb(img: Image.Image) -> Image.Image:
    small = img.copy()
    small.thumbnail((768, 768))
    return small


async def solve_with_gemini(img: Image.Image) -> str | None:
    if not client_ai:
        return None
    t0 = time.perf_counter()
    try:
        small = await asyncio.get_running_loop().run_in_executor(None, _thumb, img)
        resp = await asyncio.wait_for(
            client_ai.aio.models.generate_content(
                model=GEMINI_MODEL, contents=[GEMINI_PROMPT, small], config=_GEMINI_CFG
            ),
            timeout=GEMINI_TIMEOUT,
        )
        result = (resp.text or "").strip().upper().replace("`", "")
        log.info(f"🔎 Gemini {time.perf_counter() - t0:.2f}s: {result}")
        if "|" not in result:
            return None
        symbol, qtype = (p.strip() for p in result.split("|", 1))
        if qtype not in GEMINI_TYPES:
            return None
        return await _lookup_async(symbol, qtype)
    except asyncio.TimeoutError:
        log.warning(f"⚠️ Gemini timed out after {GEMINI_TIMEOUT:.0f}s")
    except asyncio.CancelledError:
        raise
    except Exception as e:
        log.error(f"❌ Gemini error: {e}")
    return None


async def solve_image(photo: BytesIO) -> str | None:
    """
    race     : OCR and Gemini start together, first valid answer wins (fastest).
    fallback : Gemini only after OCR fails.
    off      : OCR only.
    """
    loop = asyncio.get_running_loop()
    img = await loop.run_in_executor(None, _open_image, photo)

    tasks: list[asyncio.Task] = []
    if OCR_AVAILABLE:
        tasks.append(asyncio.create_task(solve_with_ocr(img), name="OCR"))
    if client_ai and (GEMINI_MODE == "race" or (GEMINI_MODE == "fallback" and not OCR_AVAILABLE)):
        tasks.append(asyncio.create_task(solve_with_gemini(img), name="GEMINI"))

    answer: str | None = None
    pending = set(tasks)
    try:
        while pending and answer is None:
            done, pending = await asyncio.wait(pending, return_when=asyncio.FIRST_COMPLETED)
            for t in done:
                try:
                    r = t.result()
                except Exception as e:
                    log.error(f"❌ {t.get_name()} failed: {e}")
                    continue
                if r:
                    answer = r
                    log.info(f"🏁 {t.get_name()} won the race")
                    break
    finally:
        for t in pending:
            t.cancel()

    if answer is None and GEMINI_MODE == "fallback" and client_ai and OCR_AVAILABLE:
        answer = await solve_with_gemini(img)
    return answer


# ═════════════════════════════════════════════════════════════════════════
# DISCUSSION GROUP: find the channel post's copy (PUSH first, API as backup)
# ═════════════════════════════════════════════════════════════════════════
_disc_cache: "OrderedDict[int, Message]" = OrderedDict()   # channel post id -> copy in group
_disc_waiters: dict[int, asyncio.Future] = {}


def _copy_source_id(m: Message) -> int | None:
    """If `m` (in the group) is the auto-forward of a post from TARGET_CHANNEL, return that post's id."""
    fc = getattr(m, "forward_from_chat", None)  # Pyrogram 2.0.x style
    if fc and fc.id == TARGET_CHANNEL:
        mid = getattr(m, "forward_from_message_id", None)
        if mid:
            return mid
    fo = getattr(m, "forward_origin", None)     # newer style
    if fo:
        chat = getattr(fo, "chat", None)
        if chat and chat.id == TARGET_CHANNEL:
            mid = getattr(fo, "message_id", None)
            if mid:
                return mid
    return None


def _remember_copy(post_id: int, msg: Message) -> None:
    _disc_cache[post_id] = msg
    while len(_disc_cache) > 200:
        _disc_cache.popitem(last=False)
    fut = _disc_waiters.get(post_id)
    if fut and not fut.done():
        fut.set_result(msg)


async def _discussion_via_api(client: Client, post_id: int, fut: asyncio.Future) -> None:
    """Backup lookup, in case the push update for the group copy is late or missed."""
    getter = getattr(client, "get_discussion_message", None)
    attempt = 0
    while not fut.done():
        attempt += 1
        if getter:
            try:
                dm = await getter(TARGET_CHANNEL, post_id)
                if dm:
                    _remember_copy(post_id, dm)
                    return
            except FloodWait as fw:
                await asyncio.sleep(fw.value)
            except Exception as e:
                log.debug(f"get_discussion_message not ready: {e}")
        if attempt % 3 == 0:
            try:
                async for m in client.get_chat_history(TARGET_CHAT, limit=15):
                    if _copy_source_id(m) == post_id:
                        _remember_copy(post_id, m)
                        return
            except Exception as e:
                log.debug(f"history scan failed: {e}")
        await asyncio.sleep(0.3)


async def _find_discussion_message(client: Client, post_id: int) -> Message | None:
    cached = _disc_cache.get(post_id)
    if cached:
        return cached
    fut = asyncio.get_running_loop().create_future()
    _disc_waiters[post_id] = fut
    api = asyncio.create_task(_discussion_via_api(client, post_id, fut))
    try:
        return await asyncio.wait_for(fut, DISCUSSION_MAX_WAIT)
    except asyncio.TimeoutError:
        return None
    finally:
        _disc_waiters.pop(post_id, None)
        await _cancel(api)


async def _send_answer(client: Client, disc_msg: Message | None, answer: str) -> str:
    """Reply to the post's copy in the group. Returns 'reply' or 'plain'."""
    if disc_msg is not None:
        await disc_msg.reply_text(answer, quote=True)
        return "reply"
    if REPLY_FALLBACK_TO_PLAIN:
        await client.send_message(TARGET_CHAT, answer)
        return "plain"
    raise RuntimeError("discussion copy of the post not found and plain fallback is disabled")


async def _send_with_flood_retry(client: Client, disc_msg: Message | None, answer: str) -> str:
    try:
        return await _send_answer(client, disc_msg, answer)
    except FloodWait as fw:
        log.warning(f"⏳ FloodWait {fw.value}s")
        await asyncio.sleep(fw.value)
        return await _send_answer(client, disc_msg, answer)


# ═════════════════════════════════════════════════════════════════════════
# DUPLICATE DETECTION (other PC / Codespaces / old script, same account)
# ═════════════════════════════════════════════════════════════════════════
_NUM_RE = re.compile(r"^-?\d[\d.,]*$")


async def _own_numeric_posts(client: Client, since_ts: float) -> list[tuple[int, str]]:
    found: list[tuple[int, str]] = []
    try:
        async for m in client.get_chat_history(TARGET_CHAT, limit=20):
            if m.date and m.date.timestamp() < since_ts:
                break
            txt = (m.text or "").strip()
            if getattr(m, "outgoing", False) and _NUM_RE.match(txt):
                found.append((m.id, txt))
    except Exception as e:
        log.warning(f"duplicate-guard history read failed: {e}")
    return found


async def _audit_after(client: Client, since_ts: float, mine: str) -> None:
    """Runs AFTER sending, so it costs no speed."""
    await asyncio.sleep(4)
    posts = await _own_numeric_posts(client, since_ts)
    if len(posts) > 1:
        texts = ", ".join(t for _, t in posts)
        log.error(f"🚨 DUPLICATES: this account posted {len(posts)} answers for this quiz: [{texts}] "
                  f"(mine was {mine}). ANOTHER COPY OF THE BOT IS RUNNING — stop it!")


async def _warn_other_sessions(client: Client) -> None:
    try:
        from pyrogram.raw.functions.account import GetAuthorizations

        res = await client.invoke(GetAuthorizations())
        now = time.time()
        others = []
        for a in res.authorizations:
            if getattr(a, "current", False) or getattr(a, "api_id", None) != API_ID:
                continue
            if now - getattr(a, "date_active", 0) > SESSION_WINDOW:
                continue
            ago = int((now - a.date_active) / 60)
            others.append(f"{a.device_model} / {a.platform} / ip {a.ip} ({a.country}) — active {ago} min ago")
        if others:
            log.error("🚨 OTHER COPIES OF THIS BOT MAY BE RUNNING (same API ID, same account):")
            for o in others:
                log.error(f"     • {o}")
            log.error("   Stop them (old terminals, Codespaces, other PC) or you will get double answers.")
        else:
            log.info("✅ No other recent session found for this API ID")
    except Exception as e:
        log.warning(f"session check skipped: {e}")


# ═════════════════════════════════════════════════════════════════════════
# CHANNEL POST HANDLING
# ═════════════════════════════════════════════════════════════════════════
def _post_kind(m: Message) -> str:
    if m.photo:
        return "📸 PHOTO"
    if m.video:
        return "🎬 VIDEO"
    if m.document:
        return "📄 DOCUMENT"
    if m.poll:
        return "📊 POLL"
    if m.sticker:
        return "🏷️ STICKER"
    if m.animation:
        return "🎞️ GIF"
    if m.audio or m.voice:
        return "🎵 AUDIO"
    if m.text:
        return "💬 TEXT"
    return f"📎 {m.media.name if m.media else 'OTHER'}"


def _is_image(m: Message) -> bool:
    if m.photo:
        return True
    return bool(m.document and (m.document.mime_type or "").startswith("image/"))


async def handle_channel_post(client: Client, message: Message, source: str) -> None:
    """Called by BOTH the push handler and the poller; the first to see a post wins."""
    if not _claim(("post", message.id)):
        log.info(f"   ⚠️ [{source}] SKIP #{message.id} - already processed by another handler")
        return

    preview = (message.text or message.caption or "").replace("\n", " ")[:80]
    log.info(f"📨 [{source}] CHANNEL POST #{message.id} | {_post_kind(message)} | {preview}")

    if not _is_image(message):
        log.info("   ↳ not an image — no reply")
        return

    post_ts = message.date.timestamp() if message.date else time.time() - 5
    if time.time() - post_ts > MAX_POST_AGE:
        log.info("   ↳ image is too old — no reply")
        return

    t0 = time.perf_counter()
    answer: str | None = None

    # Look for the post's copy in the group NOW, in parallel with download + solving
    disc_task = asyncio.create_task(_find_discussion_message(client, message.id))

    try:
        photo = await client.download_media(message, in_memory=True)
        t_dl = time.perf_counter()
        answer = await solve_image(photo)
        t_solve = time.perf_counter()
        if answer:
            log.info(f"   ✅ Answer {answer} | download {t_dl - t0:.2f}s | solve {t_solve - t_dl:.2f}s")
    except Exception as e:
        log.error(f"❌ Image handling error: {e}")

    if not answer:
        await _cancel(disc_task)
        log.info("   ↳ no trustworthy answer — nothing posted")
        return

    if PRE_SEND_GUARD:  # off by default: costs one extra network round trip
        existing = await _own_numeric_posts(client, post_ts - 3)
        if existing:
            texts = [t for _, t in existing]
            if answer in texts:
                await _cancel(disc_task)
                log.info(f"   ↳ another copy already posted {answer} — skipping")
                return
            log.error(f"🚨 CONFLICT: another copy posted {texts} but I computed {answer}.")

    # The copy is usually already here by now; wait only a short grace period if it isn't.
    disc_msg: Message | None = _disc_cache.get(message.id)
    if disc_msg is None:
        try:
            disc_msg = await asyncio.wait_for(asyncio.shield(disc_task), DISCUSSION_GRACE)
        except asyncio.TimeoutError:
            disc_msg = _disc_cache.get(message.id)
        except Exception as e:
            log.warning(f"⚠️ Could not locate the post in the group: {e}")
    await _cancel(disc_task)

    if disc_msg is None:
        log.warning("⚠️ Discussion copy of the post NOT found — "
                    + ("posting a plain message" if REPLY_FALLBACK_TO_PLAIN else "not posting"))

    t_send = time.perf_counter()
    try:
        mode = await _send_with_flood_retry(client, disc_msg, answer)
        label = "as REPLY to the post" if mode == "reply" else "as plain message"
        now = time.perf_counter()
        log.info(f"🚀 POSTED {answer} {label} | send {now - t_send:.2f}s | TOTAL {now - t0:.2f}s "
                 f"(since the bot saw the post)")
        _spawn(_audit_after(client, post_ts - 3, answer))
    except Exception as e:
        log.error(f"❌ Failed to post to group: {e}")


@app.on_message(filters.chat(TARGET_CHANNEL), group=0)
async def on_channel_message(client: Client, message: Message):
    await handle_channel_post(client, message, "PUSH")


@app.on_message(filters.chat(TARGET_CHAT), group=1)
async def on_group_message(client: Client, message: Message):
    # Instantly remember the auto-forwarded copy of every channel post (this is what we reply to)
    src = _copy_source_id(message)
    if src is not None:
        _remember_copy(src, message)

    if SHOW_GROUP_MESSAGES:
        who = (message.from_user.first_name if message.from_user
               else message.sender_chat.title if message.sender_chat else "?")
        preview = (message.text or message.caption or "").replace("\n", " ")[:60]
        log.info(f"   💬 [GROUP] #{message.id} {_post_kind(message)} from {who}: {preview}")


# ── Optional hype message ────────────────────────────────────────────────
HYPE_MESSAGES = ["Let's gooo! 🔥", "LET'S GO! 💪", "Ready! Let's goooo! 🚀", "ተዘጋጅቻለሁ! 🔥"]
HYPE_KEYWORDS = ["ተዘጋጁ", "ይቀርባል", "quiz time", "get ready"]
_last_hype = 0.0


@app.on_message(filters.chat(TARGET_CHANNEL) & filters.text, group=2)
async def hype_handler(client: Client, message: Message):
    global _last_hype
    if not HYPE_ENABLED:
        return
    low = (message.text or "").lower()
    if not any(k in low for k in HYPE_KEYWORDS):
        return
    if time.time() - _last_hype < 600 or not _claim(("hype", message.id)):
        return
    _last_hype = time.time()
    await asyncio.sleep(random.uniform(2, 4))
    try:
        await client.send_message(TARGET_CHAT, random.choice(HYPE_MESSAGES))
    except Exception as e:
        log.error(f"❌ Hype error: {e}")


# ═════════════════════════════════════════════════════════════════════════
# POLLING SAFETY NET + KEEP ONLINE
# ═════════════════════════════════════════════════════════════════════════
async def _poll_channel(client: Client) -> None:
    log.info(f"🔄 Polling safety net started (every {POLL_INTERVAL:.1f}s)")
    last_seen: int | None = None
    delay = POLL_INTERVAL

    while True:
        try:
            _maybe_reload_json()
            new: list[Message] = []
            async for msg in client.get_chat_history(TARGET_CHANNEL, limit=5):
                if last_seen is not None and msg.id <= last_seen:
                    break
                new.append(msg)

            if last_seen is None:
                last_seen = new[0].id if new else 0
                for m in new:
                    _claim(("post", m.id))  # seed only; never answer old posts
                log.info(f"🔄 Poll seeded at #{last_seen}")
            else:
                for msg in reversed(new):
                    last_seen = max(last_seen, msg.id)
                    _spawn(handle_channel_post(client, msg, "POLL"))  # never blocks the poller
            delay = POLL_INTERVAL
        except FloodWait as fw:
            await asyncio.sleep(fw.value + 1)
            continue
        except Exception as e:
            log.warning(f"🔄 Poll error: {e} — retry in {delay:.0f}s")
            delay = min(delay * 2, 30)
        await asyncio.sleep(delay)


async def _keep_online(client: Client) -> None:
    from pyrogram.raw.functions.account import UpdateStatus

    while True:
        try:
            await client.invoke(UpdateStatus(offline=False))
        except FloodWait as fw:
            await asyncio.sleep(fw.value)
        except Exception as e:
            log.warning(f"🟢 keep_online error: {e}")
        await asyncio.sleep(240)


async def _warm_up() -> None:
    """First Tesseract call / first HTTPS handshake are slow; pay that cost at startup, not on quiz time."""
    loop = asyncio.get_running_loop()
    if OCR_AVAILABLE:
        try:
            t = time.perf_counter()
            await loop.run_in_executor(OCR_POOL, _ocr_pass, Image.new("L", (300, 80), 255), False, 6)
            log.info(f"🔥 OCR warmed up in {time.perf_counter() - t:.2f}s")
        except Exception as e:
            log.debug(f"OCR warm-up failed: {e}")
    if client_ai and GEMINI_MODE != "off":
        try:
            t = time.perf_counter()
            await asyncio.wait_for(
                client_ai.aio.models.generate_content(model=GEMINI_MODEL, contents="ok", config=_GEMINI_CFG),
                timeout=10,
            )
            log.info(f"🔥 Gemini connection warmed up in {time.perf_counter() - t:.2f}s")
        except Exception as e:
            log.debug(f"Gemini warm-up failed: {e}")


# ═════════════════════════════════════════════════════════════════════════
# STARTUP / MAIN
# ═════════════════════════════════════════════════════════════════════════
async def _startup_checks(client: Client) -> None:
    log.info("🔍 STARTUP CHECKS")
    found = {TARGET_CHANNEL: False, TARGET_CHAT: False}
    try:
        async for dialog in client.get_dialogs():
            if dialog.chat.id in found:
                found[dialog.chat.id] = True
                log.info(f"   ✅ Found: {dialog.chat.title} ({dialog.chat.id})")
    except Exception as e:
        log.error(f"   ❌ Error loading dialogs: {e}")

    for chat_id, ok in found.items():
        if ok:
            continue
        try:
            ch = await client.get_chat(chat_id)
            log.info(f"   ✅ Resolved: {ch.title}")
        except ChannelPrivate:
            sys.exit(f"❌ {chat_id} is private and this account is not a member — join it in the Telegram app.")
        except PeerIdInvalid:
            sys.exit(f"❌ {chat_id}: peer id invalid — check the ID in .env.")
        except Exception as e:
            sys.exit(f"❌ Cannot resolve {chat_id}: {e}")

    try:
        ch = await client.get_chat(TARGET_CHANNEL)
        linked = getattr(ch, "linked_chat", None)
        if linked and linked.id != TARGET_CHAT:
            log.error(f"🚨 TARGET_CHAT ({TARGET_CHAT}) is NOT the channel's linked discussion group "
                      f"({linked.id}). Replies to posts will not work until you fix .env.")
        elif linked:
            log.info("   ✅ TARGET_CHAT is the linked discussion group of the channel")
        else:
            log.warning("   ⚠️ Could not confirm the channel's linked discussion group")
    except Exception as e:
        log.warning(f"   ⚠️ Linked-group check skipped: {e}")

    me = await client.get_me()
    log.info(f"👤 Logged in as: {me.first_name} (@{me.username or 'no-username'})")
    await _warn_other_sessions(client)
    log.info(
        f"✅ Watching channel {TARGET_CHANNEL} | replying to image posts in group {TARGET_CHAT}\n"
        f"   Gemini: {GEMINI_MODE.upper()} | OCR workers: {OCR_WORKERS} | Poll: {POLL_INTERVAL:.1f}s | "
        f"Plain fallback: {'ON' if REPLY_FALLBACK_TO_PLAIN else 'OFF'} | "
        f"Pre-send guard: {'ON' if PRE_SEND_GUARD else 'OFF'} | "
        f"Data: {'MT5 live' if MT5_AVAILABLE else 'JSON ' + str(_json_meta['generated_at'])}"
    )


def _single_instance_lock() -> socket.socket:
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        s.bind(("127.0.0.1", LOCK_PORT))
    except OSError:
        sys.exit("❌ Another copy of this bot is already running on this machine. Close it first.")
    return s


async def main() -> None:
    json_loaded = load_json_prices()

    if MT5_AVAILABLE:
        if ensure_mt5():
            log.info("✅ MT5 connected")
            _pre_warm_cache()
        else:
            log.warning(f"⚠️ MT5 not ready: {mt5.last_error()}")
            if not json_loaded:
                sys.exit("❌ No MT5 and no JSON data available!")
    elif not json_loaded:
        sys.exit("❌ No mt5_prices.json — run price_generator.py on the MT5 PC first.")

    await app.start()
    await _startup_checks(app)

    tasks = [
        asyncio.create_task(_poll_channel(app)),
        asyncio.create_task(_keep_online(app)),
        asyncio.create_task(_warm_up()),
    ]
    log.info("🤖 Bot is running. Press Ctrl+C to stop.")
    try:
        await idle()
    finally:
        for t in tasks:
            t.cancel()
        await app.stop()
        OCR_POOL.shutdown(wait=False, cancel_futures=True)
        if MT5_AVAILABLE and _mt5_initialized:
            mt5.shutdown()
        log.info("👋 Bot stopped.")


if __name__ == "__main__":
    if len(sys.argv) >= 3 and sys.argv[1] == "--test":
        load_json_prices()
        if MT5_AVAILABLE:
            ensure_mt5()
        with open(sys.argv[2], "rb") as fh:
            t_start = time.perf_counter()
            result = asyncio.run(solve_image(BytesIO(fh.read())))
            print(f"\n➡️ ANSWER: {result}   ({time.perf_counter() - t_start:.2f}s)")
        sys.exit(0)

    _lock = _single_instance_lock()
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n👋 Bye!")