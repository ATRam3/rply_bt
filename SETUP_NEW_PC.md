# 🚀 Setup Guide - Run Bot on New PC

## Prerequisites

You need these installed on the new PC:

### 1. **Python 3.10 to 3.12** (NOT 3.13+!)
Download from: https://www.python.org/downloads/

**⚠️ IMPORTANT:**
- Python 3.15 is TOO NEW - MetaTrader5 doesn't support it yet
- Use Python 3.10, 3.11, or 3.12 (recommended: 3.11)
- Download link: https://www.python.org/downloads/release/python-3119/
- Check "Add Python to PATH" during installation!

### 2. **MetaTrader 5 Terminal**
Download from: https://www.metatrader5.com/en/download

**Required:** Must be installed and logged in with your broker account (Exness)

### 3. **Git** (Optional, for cloning)
Download from: https://git-scm.com/downloads

---

## Setup Steps

### Step 1: Copy Files to New PC

Copy the entire `replay_bot` folder to the new PC. You need:

```
replay_bot/
├── bot.py                          ← Main bot code
├── .env                            ← Your credentials (COPY THIS!)
├── .env.example                    ← Template
├── get_id.py                       ← Utility
├── requirements.txt                ← Package list
├── fast_image_userbot.session      ← Telegram session (COPY THIS!)
├── sister_bot.session              ← Telegram session (if used)
└── downloads/                      ← Create this folder
```

**Critical Files to Copy:**
- ✅ `.env` - Contains your API keys
- ✅ `*.session` files - Telegram login sessions

---

### Step 2: Install Python Packages

Open Command Prompt or Terminal in the `replay_bot` folder and run:

```bash
pip install -r requirements.txt
```

This installs:
- `pyrogram` - Telegram client
- `TgCrypto` - Fast encryption for Telegram
- `google-genai` - Google Gemini AI
- `Pillow` - Image processing
- `MetaTrader5` - Trading data
- `pandas` - Data manipulation
- `python-dotenv` - Environment variables

---

### Step 3: Setup MetaTrader 5

1. **Install MT5** from https://www.metatrader5.com/en/download
2. **Login** with your Exness account
3. **Enable Algo Trading**:
   - Tools → Options → Expert Advisors
   - Check "Allow automated trading"
   - Check "Allow DLL imports"
4. **Keep MT5 Running** (minimize it, don't close)

---

### Step 4: Verify .env File

Open `.env` and make sure it has your credentials:

```env
TELEGRAM_API_ID=your_api_id_here
TELEGRAM_API_HASH=your_api_hash_here
GEMINI_API_KEY=your_gemini_key_here
TARGET_CHAT=-1002385736403
GEMINI_MODEL=gemini-3.5-flash-lite
```

**If you don't have these:**

#### Get Telegram API Credentials:
1. Go to https://my.telegram.org/auth
2. Login with your phone number
3. Go to "API Development Tools"
4. Create an app, get `api_id` and `api_hash`

#### Get Gemini API Key:
1. Go to https://aistudio.google.com/apikey
2. Create an API key
3. Copy it to `.env`

---

### Step 5: Test the Bot

Run a quick test:

```bash
python bot.py
```

You should see:
```
🤖 Initializing MT5 connection...
✅ MT5 Connected!
📊 Pre-warming cache...
  ✅ Cached XAUUSDm
  ✅ Cached GBPJPYm
  ... (more tickers)
🤖 Listening for images on -1002385736403...
```

**If you see errors:**

❌ **"MT5 initialization failed"**
- Solution: Make sure MT5 is running and logged in

❌ **"Module not found"**
- Solution: Run `pip install -r requirements.txt` again

❌ **"403 PERMISSION_DENIED" (Gemini)**
- Solution: Check your `GEMINI_API_KEY` in `.env`

---

## Important Notes

### 🔐 Session Files
The `*.session` files contain your Telegram login. If you don't copy them:
- First run will ask for your phone number
- You'll get a verification code via Telegram
- Enter it to create a new session

### 📊 MT5 Connection
- MT5 must be **running and logged in**
- If you close MT5, the bot won't work
- Keep MT5 minimized in the background

### 🌐 Internet Connection
- Bot needs internet for:
  - Telegram (download images, send replies)
  - Gemini API (analyze questions)
- Faster internet = faster bot responses

### 💾 Cached Data
- First run: Bot caches 16 tickers (~2 seconds)
- After that: Instant lookups from cache
- Cache refreshes every 2 minutes

---

## Troubleshooting

### Problem: "No module named 'pyrogram'"
```bash
pip install pyrogram TgCrypto
```

### Problem: "No module named 'MetaTrader5'"
```bash
pip install MetaTrader5
```

### Problem: MT5 won't connect
1. Check MT5 is running
2. Check you're logged in to your broker
3. Try restarting MT5

### Problem: Bot doesn't reply to messages
1. Check `TARGET_CHAT` in `.env` is correct
2. Make sure bot is added to the channel
3. Check console for "⚡ [IMAGE POST" messages

---

## Running the Bot

### Windows:
```bash
cd C:\path\to\replay_bot
python bot.py
```

### Linux/Mac:
```bash
cd /path/to/replay_bot
python3 bot.py
```

### Run in Background (Windows):
```bash
start /B python bot.py
```

### Run in Background (Linux):
```bash
nohup python3 bot.py > bot.log 2>&1 &
```

---

## Expected Performance

With good internet (50+ Mbps):
- ✅ **5-6 seconds** per question
- ✅ **99%+ accuracy** for 16 pre-loaded tickers
- ✅ **Smart skipping** for unsupported questions

---

## What the Bot Handles

### ✅ Supported Tickers (16):
- **Forex:** XAUUSD, GBPJPY, GBPUSD, EURUSD, USDJPY, BTCUSD, EURJPY, AUDUSD, USDCAD, NZDUSD, USDCHF, GBPCHF
- **Indices:** NASDAQ/USTECH100, US500, US30
- **Commodities:** XAGUSD (Silver)

### ✅ Supported Question Types:
- This week's lowest/highest price
- Last week's lowest/highest price
- Period lowest/highest price
- Latest close price

### ❌ Skips:
- Unsupported tickers (EURNZD, etc.)
- Unsupported questions (opening price, volume, etc.)

---

## Need Help?

Check the console output - it tells you exactly what's happening:
- ✅ Success: `⚡ Answered in 5.2s | 208.355`
- ⚠️ Skipped: `⚠️ Ticker not in pre-loaded list - skipping`
- ❌ Error: Shows the exact error message

---

## Summary Checklist

Before running on new PC:

- [ ] Python 3.10+ installed
- [ ] MT5 installed and logged in
- [ ] All files copied (especially `.env` and `.session`)
- [ ] Packages installed (`pip install -r requirements.txt`)
- [ ] `.env` has correct credentials
- [ ] MT5 is running
- [ ] Internet connection is working

Then run: `python bot.py` 🚀
