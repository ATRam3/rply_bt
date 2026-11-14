"""
Check if multiple bot instances are running
"""
import socket

def check_bot_running():
    """Try to bind to the bot's lock port"""
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        s.bind(("127.0.0.1", 47831))
        s.close()
        print("✅ NO bot is currently running")
        return False
    except OSError as e:
        print(f"🔴 ANOTHER BOT IS RUNNING!")
        print(f"   Error: {e}")
        print(f"   Port 47831 is already in use")
        print(f"\n💡 To fix:")
        print(f"   1. Close all terminal windows")
        print(f"   2. Open Task Manager (Ctrl+Shift+Esc)")
        print(f"   3. End all 'python.exe' processes")
        print(f"   4. Restart your bot")
        return True

if __name__ == "__main__":
    print("=" * 60)
    print("🔍 Checking for duplicate bot instances...")
    print("=" * 60)
    check_bot_running()
