import os
from dotenv import load_dotenv
import requests

load_dotenv()

# Test each token
tokens = {
    "VALKYRIEMENU_BOT_TOKEN": os.getenv("VALKYRIEMENU_BOT_TOKEN"),
    "VALKYRIEGROUPMOD_BOT_TOKEN": os.getenv("VALKYRIEGROUPMOD_BOT_TOKEN"),
    "VALKYRIESELLERBUYER_BOT_TOKEN": os.getenv("VALKYRIESELLERBUYER_BOT_TOKEN"),
    "VALKYRIEPOSTER1249_BOT_TOKEN": os.getenv("VALKYRIEPOSTER1249_BOT_TOKEN"),
    "VALKYRIEWELCOME_BOT_TOKEN": os.getenv("VALKYRIEWELCOME_BOT_TOKEN"),
    "VALKYRIEMOTHER_BOT_TOKEN": os.getenv("VALKYRIEMOTHER_BOT_TOKEN"),
}

print("🔍 Testing bot tokens...")
for name, token in tokens.items():
    if not token:
        print(f"❌ {name}: MISSING")
        continue
        
    try:
        url = f"https://api.telegram.org/bot{token}/getMe"
        response = requests.get(url, timeout=5)
        
        if response.status_code == 200:
            data = response.json()
            if data.get("ok"):
                bot_info = data["result"]
                print(f"✅ {name}: @{bot_info['username']} - {bot_info['first_name']}")
            else:
                print(f"❌ {name}: {data.get('description', 'Unknown error')}")
        else:
            print(f"❌ {name}: HTTP {response.status_code}")
            
    except Exception as e:
        print(f"❌ {name}: {str(e)}")

print("\n🔍 Testing environment variables...")
print(f"Python version: {os.sys.version}")
print(f"Current directory: {os.getcwd()}")

# Test if we can import telegram
try:
    import telegram
    print(f"✅ python-telegram-bot version: {telegram.__version__}")
except Exception as e:
    print(f"❌ Failed to import telegram: {e}")
