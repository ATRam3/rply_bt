"""
Hype Bot - Auto-reply to quiz announcements
Detects "ready" announcements and posts hype messages!
"""

import asyncio
import sys
import os
import random
from dotenv import load_dotenv

# Fix Windows terminal encoding
if sys.stdout.encoding != 'utf-8':
    sys.stdout.reconfigure(encoding='utf-8')

# Load credentials from .env file
load_dotenv()

from pyrogram import Client, filters
from pyrogram.types import Message

# Credentials
API_ID = int(os.getenv("TELEGRAM_API_ID"))
API_HASH = os.getenv("TELEGRAM_API_HASH")
TARGET_CHANNEL = int(os.getenv("TARGET_CHANNEL"))
TARGET_CHAT = int(os.getenv("TARGET_CHAT"))

# Initialize Telegram Userbot (use different session name to avoid lock)
app = Client("hype_userbot", api_id=API_ID, api_hash=API_HASH)

# Hype messages to randomly choose from
HYPE_MESSAGES = [
    "Let's gooo! 🔥",
    "LET'S GO! 💪",
    "Ready! Let's goooo! 🚀",
    "Let's go! Time to win! 🏆",
    "LETS GOOOOO! 🔥🔥🔥",
    "Let's goooo! 💯",
    "I'm ready! Let's go! ⚡",
    "Let's go! 🎯",
    "READY! LET'S GOOO! 🚀",
    "ተዘጋጅቻለሁ! 🔥",  # "I'm ready!" in Amharic
    "Let's win this! 💪🏆",
]

@app.on_message(filters.chat(TARGET_CHANNEL) & filters.text)
async def detect_ready_announcement(client: Client, message: Message):
    """Detect 'ready' announcement and reply with hype!"""
    
    # Get message text
    text = message.text if message.text else ""
    
    # Keywords that indicate quiz is starting (English + Amharic)
    ready_keywords = [
        # English
        "ready", "starts", "starting", "begin", "get ready", "20$", "quiz time",
        # Amharic (Ethiopian)
        "20$", "ዶላር", "ጥያቄ", "ደቂቃ", "ተዘጋጁ",  # "dollar", "question", "minute", "get ready"
        "ይቀርባል",  # "will be presented"
    ]
    
    # Check if this is a quiz announcement
    is_announcement = any(keyword in text for keyword in ready_keywords)
    
    # Special check for the exact message you showed
    if "20$" in text and "ዶላር" in text:
        is_announcement = True
    
    if is_announcement:
        print(f"\n{'='*60}")
        print(f"🎯 QUIZ ANNOUNCEMENT DETECTED!")
        print(f"{'='*60}")
        print(f"📝 Text: {text}")
        
        # Wait 2-5 seconds (look natural, not instant)
        wait_time = random.uniform(2, 5)
        print(f"⏳ Waiting {wait_time:.1f}s before replying...")
        await asyncio.sleep(wait_time)
        
        # Choose random hype message
        hype = random.choice(HYPE_MESSAGES)
        
        try:
            # Post in CHAT GROUP (not channel)
            await client.send_message(TARGET_CHAT, hype)
            print(f"✅ Posted: {hype}")
            print(f"{'='*60}\n")
        except Exception as e:
            print(f"❌ Error posting: {e}")


@app.on_message(filters.chat(TARGET_CHAT) & filters.text)
async def react_to_others_hype(client: Client, message: Message):
    """React to other people's hype messages (optional)"""
    
    # Don't react to own messages
    if message.from_user and message.from_user.is_self:
        return
    
    text = message.text.lower()
    
    # If someone else says "let's go", maybe react too (10% chance)
    if "let's go" in text or "lets go" in text or "ready" in text:
        # Only react 10% of the time (don't spam)
        if random.random() < 0.1:
            reactions = ["🔥", "💪", "🚀", "🎯", "⚡"]
            reaction = random.choice(reactions)
            
            try:
                await message.react(reaction)
                print(f"👍 Reacted with {reaction} to hype message")
            except:
                pass  # Reactions might not be available


async def main():
    """Start the hype bot"""
    print("\n" + "="*60)
    print("🎉 HYPE BOT STARTED!")
    print("="*60)
    print(f"📢 Monitoring channel: {TARGET_CHANNEL}")
    print(f"💬 Will post in chat: {TARGET_CHAT}")
    print("="*60)
    print("\n⏳ Waiting for quiz announcements...\n")
    
    await app.start()
    await asyncio.Event().wait()


if __name__ == "__main__":
    try:
        app.run(main())
    except KeyboardInterrupt:
        print("\n\n👋 Hype bot stopped!")
