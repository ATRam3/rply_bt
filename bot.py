import os
import asyncio
from pyrogram import Client, filters
from pyrogram.types import Message
import google.genai as genai
from PIL import Image
import requests

# 1. YOUR CREDENTIALS
API_ID = TELEGRAM_API_ID_VALUE                          # Your Telegram API ID
API_HASH = "TELEGRAM_API_HASH_VALUE" # Your Telegram API Hash
GEMINI_API_KEY = "GEMINI_KEY_VALUE" # Your Gemini API Key
TWELVE_DATA_API_KEY = "TWELVE_DATA_KEY_VALUE" # Your Twelve Data API Key

# 2. TARGET CHANNEL
TARGET_CHAT = -1002385736403               # Your target chat numeric ID

# Initialize Google GenAI Client
client_ai = genai.Client(api_key=GEMINI_API_KEY)

# Initialize Telegram Userbot Session
app = Client("fast_image_userbot", api_id=API_ID, api_hash=API_HASH)

def get_market_data_answer(ticker_symbol: str) -> str:
    """Fetches accurate institutional spot market data using the Twelve Data API."""
    try:
        clean_symbol = ticker_symbol.strip().upper().replace("=", "").replace("-", "").replace("/", "")
        
        # Format symbol for Twelve Data spot format (e.g. XAU/USD, EUR/USD)
        if clean_symbol in ["XAUUSD", "GOLD"]:
            query_symbol = "XAU/USD"
        elif clean_symbol in ["XAGUSD", "SILVER"]:
            query_symbol = "XAG/USD"
        elif clean_symbol == "BTCUSD":
            query_symbol = "BTC/USD"
        elif clean_symbol == "ETHUSD":
            query_symbol = "ETH/USD"
        elif len(clean_symbol) == 6 and clean_symbol.isalpha():
            query_symbol = f"{clean_symbol[:3]}/{clean_symbol[3:]}"
        else:
            query_symbol = clean_symbol

        url = f"https://api.twelvedata.com/time_series?symbol={query_symbol}&interval=1day&outputsize=7&apikey={TWELVE_DATA_API_KEY}"
        print(f"📊 [FETCHING TWELVE DATA FOR]: {query_symbol}")
        
        response = requests.get(url)
        data = response.json()
        
        if "values" in data:
            values = data["values"]
            lows = [float(item["low"]) for item in values]
            highs = [float(item["high"]) for item in values]
            closes = [float(item["close"]) for item in values]
            
            lowest_price = min(lows)
            highest_price = max(highs)
            current_price = closes[0]
            
            return (
                f"Live Spot Market Data for {query_symbol}:\n"
                f"- Lowest price this week: {lowest_price:.3f}\n"
                f"- Highest price this week: {highest_price:.3f}\n"
                f"- Current price: {current_price:.3f}"
            )
        else:
            print(f"⚠️ Twelve Data API message: {data.get('message', data)}")
    except Exception as e:
        print(f"❌ Twelve Data fetch error for {ticker_symbol}: {e}")
    return None

def solve_question_image(image_path: str) -> str:
    """Extracts ticker & question from image, pulls live Twelve Data spot feeds, and solves it."""
    try:
        img = Image.open(image_path)
        
        # Step 1: Extract question and ticker from image
        extract_prompt = (
            "Analyze this trading quiz image. "
            "1. Identify the asset symbol/ticker being asked about (e.g., EURUSD, XAUUSD, BTCUSD, GBPUSD). "
            "2. Identify the exact question text. "
            "Output strictly in this format: TICKER: <symbol> | QUESTION: <question text>"
        )
        query_response = client_ai.models.generate_content(
            model='gemini-3.5-flash-lite',
            contents=[extract_prompt, img]
        )
        extracted_text = query_response.text.strip()
        print(f"🔎 [EXTRACTED DATA]: {extracted_text}")
        
        ticker_symbol = "XAUUSD" # default fallback
        question_text = extracted_text
        
        if "|" in extracted_text:
            parts = extracted_text.split("|")
            for part in parts:
                if "TICKER:" in part:
                    ticker_symbol = part.replace("TICKER:", "").strip()
                elif "QUESTION:" in part:
                    question_text = part.replace("QUESTION:", "").strip()

        # Step 2: Fetch live spot market data from Twelve Data
        market_context = get_market_data_answer(ticker_symbol)
        
        # Step 3: Solve using text ONLY (passing spot numbers + question)
        if market_context:
            final_prompt = (
                f"Official Market Context (Twelve Data): {market_context}\n\n"
                f"Question: {question_text}\n\n"
                "Note: The question refers to the Exness terminal chart. "
                "Using the provided market low as a primary reference, output ONLY the exact numerical figure."
            )
        else:
            final_prompt = (
                f"Question: {question_text}\n"
                "Provide ONLY the correct, direct answer clearly and concisely."
            )

        response = client_ai.models.generate_content(
            model='gemini-3.5-flash-lite',
            contents=[final_prompt]
        )
        return response.text.strip()
        
    except Exception as e:
        return f"Error analyzing image: {e}"

@app.on_message(filters.chat(TARGET_CHAT) & (filters.photo | filters.text))
async def handle_incoming_post(client: Client, message: Message):
    print(f"\n⚡ [NEW POST DETECTED - ID: {message.id}] Processing...")

    file_path = None 
    answer = ""

    # Process photo
    if message.photo:
        print("📸 Downloading photo...")
        file_path = await message.download()
        try:
            print("🔍 [SOLVING] Processing image and Twelve Data spot feeds...")
            answer = solve_question_image(file_path)
            print(f"✅ [ANSWER GENERATED]: {answer}")
        finally:
            if file_path and os.path.exists(file_path):
                os.remove(file_path)

    # Process text
    elif message.text:
        print(f"📝 Text Question Detected: {message.text[:50]}...")
        try:
            response = client_ai.models.generate_content(
                model='gemini-3.5-flash-lite',
                contents=[f"Provide ONLY the direct answer to this question: {message.text}"]
            )
            answer = response.text.strip()
            print(f"✅ [ANSWER GENERATED]: {answer}")
        except Exception as e:
            print(f"Error: {e}")

    # Send comment specifically into the discussion thread
    if answer and "RESOURCE_EXHAUSTED" not in answer:
        try:
            await client.send_message(
                chat_id=message.chat.id,
                text=answer,
                reply_to_message_id=message.id
            )
            print("🚀 [COMMENT PLACED INSIDE 'LEAVE A COMMENT' PANEL!]")
        except Exception as e:
            print(f"❌ Error sending comment: {e}")
    else:
        print("⚠️ Skipped posting due to API rate limit or error.")

if __name__ == "__main__":
    print(f"🤖 Userbot listening on {TARGET_CHAT} for comments...")
    app.run()