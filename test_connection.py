"""
Test if your bot can see the real EyuelFxTrading channel
Run this to verify BEFORE Saturday!
"""
import asyncio
from pyrogram import Client
from dotenv import load_dotenv
import os

load_dotenv()

API_ID = int(os.getenv("TELEGRAM_API_ID"))
API_HASH = os.getenv("TELEGRAM_API_HASH")
TARGET_CHANNEL = int(os.getenv("TARGET_CHANNEL"))
TARGET_CHAT = int(os.getenv("TARGET_CHAT"))

app = Client("fast_image_userbot", api_id=API_ID, api_hash=API_HASH)

async def test_connection():
    await app.start()
    
    print("\n" + "="*60)
    print("🔍 TESTING BOT CONNECTION")
    print("="*60)
    
    # Test 1: Can we access the channel?
    try:
        channel = await app.get_chat(TARGET_CHANNEL)
        print(f"\n✅ TEST 1: Channel Access")
        print(f"   Name: {channel.title}")
        print(f"   ID: {channel.id}")
        print(f"   Type: {channel.type}")
        if channel.username:
            print(f"   Username: @{channel.username}")
    except Exception as e:
        print(f"\n❌ TEST 1 FAILED: Cannot access channel!")
        print(f"   Error: {e}")
        print(f"   → You're probably NOT in this channel!")
        await app.stop()
        return
    
    # Test 2: Can we read messages?
    try:
        print(f"\n✅ TEST 2: Reading Last 5 Messages from Channel")
        count = 0
        async for message in app.get_chat_history(TARGET_CHANNEL, limit=5):
            count += 1
            msg_type = "PHOTO" if message.photo else "TEXT" if message.text else "OTHER"
            text_preview = ""
            if message.text:
                text_preview = message.text[:50]
            elif message.caption:
                text_preview = message.caption[:50]
            
            print(f"   {count}. [{msg_type}] {text_preview}")
        
        if count == 0:
            print(f"   ⚠️  No messages found (channel might be empty)")
    except Exception as e:
        print(f"\n❌ TEST 2 FAILED: Cannot read messages!")
        print(f"   Error: {e}")
        print(f"   → Channel might be private or restricted!")
        await app.stop()
        return
    
    # Test 3: Can we send to chat group?
    try:
        chat = await app.get_chat(TARGET_CHAT)
        print(f"\n✅ TEST 3: Chat Group Access")
        print(f"   Name: {chat.title}")
        print(f"   ID: {chat.id}")
    except Exception as e:
        print(f"\n❌ TEST 3 FAILED: Cannot access chat group!")
        print(f"   Error: {e}")
    
    print("\n" + "="*60)
    print("🎯 FINAL VERDICT")
    print("="*60)
    print("\nIf ALL 3 tests passed:")
    print("✅ Your bot WILL work on Saturday!")
    print("✅ Just start it 30 min before quiz")
    print("\nIf ANY test failed:")
    print("❌ You need to fix that issue first!")
    print("❌ Check SETUP_NEW_PC.md for solutions")
    print("="*60)
    
    await app.stop()

if __name__ == "__main__":
    app.run(test_connection())
