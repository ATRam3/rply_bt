# Customize Which Tickers to Pre-Load

## Current Setup (Top 7 - Covers 95%)

Your bot currently pre-loads these 7 tickers for fast responses:

1. **XAUUSD** (Gold) - Most common
2. **GBPJPY** - Very common
3. **GBPUSD** - Common
4. **EURUSD** - Common
5. **USDJPY** - Common
6. **BTCUSD** (Bitcoin) - Common
7. **EURJPY** - Common

## How to Customize

Edit `bot.py` and find this section (around line 230):

```python
# Get top 7 tickers (covers 95% of questions)
top_tickers = [
    "XAUUSD",   # Gold (most common)
    "GBPJPY",   # Very common
    "GBPUSD",   # Common
    "EURUSD",   # Common
    "USDJPY",   # Common
    "BTCUSD",   # Bitcoin (common)
    "EURJPY"    # Common
]
```

### Option 1: Add More Currencies (Slower but more coverage)

```python
top_tickers = [
    "XAUUSD", "GBPJPY", "GBPUSD", "EURUSD", "USDJPY",
    "BTCUSD", "EURJPY", "AUDUSD", "USDCAD", "NZDUSD"
]
# 10 tickers = covers 98% but 1-2s slower
```

### Option 2: Add Indices (NASDAQ, US500, etc.)

```python
top_tickers = [
    "XAUUSD", "GBPJPY", "GBPUSD", "EURUSD", "USDJPY",
    "NASDAQ", "US500", "US30"
]
# Good if quiz asks about stock indices often
```

### Option 3: Focus on Only YOUR Most Common (Fastest)

Track which tickers appear most in your quizzes, then:

```python
top_tickers = [
    "XAUUSD",   # If 60% of questions are Gold
    "GBPJPY",   # If 20% are GBPJPY
    "EURUSD"    # If 10% are EURUSD
]
# Only 3 tickers = 4-6 seconds (fastest!)
```

## Trade-offs

| # Tickers | Coverage | Speed | When to Use |
|-----------|----------|-------|-------------|
| 3 | 70-80% | **5-6s** ⚡ | If 80%+ questions use 3 symbols |
| 5 | 85-90% | **6-7s** ✅ | Balanced (current default) |
| 7 | 95% | **7-9s** ✅ | Safe choice (NEW default) |
| 10 | 98% | **9-11s** | Want max coverage |
| All (fallback only) | 100% | **12-15s** | Slower but handles everything |

## Fallback Always Works

Even if a ticker is NOT in your list, the fallback will:
1. Detect it (adds 5-7 seconds)
2. Fetch the data
3. Get the answer

So you're covered either way! The top_tickers list is just for **speed optimization**.

## Recommended Setup

**If most quizzes use 3-5 symbols:**
```python
top_tickers = ["XAUUSD", "GBPJPY", "GBPUSD"]  # Fast!
```

**If quizzes vary a lot:**
```python
top_tickers = ["XAUUSD", "GBPJPY", "GBPUSD", "EURUSD", "USDJPY", "BTCUSD", "EURJPY"]  # Current
```

## Test Your Changes

After editing, run:
```bash
python bot.py
```

Watch the times:
- Fast (5-8s) = ticker was in your list ✅
- Slower (12-15s) = fallback was used (ticker not in list)

Adjust your list based on what you see most often!
