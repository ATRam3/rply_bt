"""
Find EyuelFxTrading channel IDs automatically
"""
import asyncio
from pyrogram import Client
from dotenv import load_dotenv
import os

load_dotenv()

API_ID = int(os.getenv("TELEGRAM_API_ID"))
API_HASH = os.getenv("TELEGRAM_API_HASH")

app = Client("fast_image_userbot", api_id=API_ID, api_hash=API_HASH)

async def find_channels():
    await app.start()
    
    print("=" * 60)
    print("🔍 Searching for EyuelFxTrading channels...")
    print("=" * 60)
    print()
    
    # Search for the main channel
    try:
        channel = await app.get_chat("@EyuelFxTrading")
        print(f"✅ MAIN CHANNEL FOUND:")
        print(f"   Name: {channel.title}")
        print(f"   Username: @{channel.username}")
        print(f"   ID: {channel.id}")
        print(f"   Type: {channel.type}")
        print()
        main_channel_id = channel.id
    except Exception as e:
        print(f"❌ Could not find @EyuelFxTrading: {e}")
        main_channel_id = None
    
    # Search for the chat group
    try:
        chat = await app.get_chat("@EyuelFxTradingchat")
        print(f"✅ CHAT GROUP FOUND:")
        print(f"   Name: {chat.title}")
        print(f"   Username: @{chat.username}")
        print(f"   ID: {chat.id}")
        print(f"   Type: {chat.type}")
        print()
        chat_id = chat.id
    except Exception as e:
        print(f"❌ Could not find @EyuelFxTradingchat: {e}")
        chat_id = None
    
    # Show what to put in .env
    print("=" * 60)
    print("📝 Copy these to your .env file:")
    print("=" * 60)
    if main_channel_id:
        print(f"TARGET_CHANNEL={main_channel_id}")
    if chat_id:
        print(f"TARGET_CHAT={chat_id}")
    print("=" * 60)
    
    await app.stop()

if __name__ == "__main__":
    app.run(find_channels())
