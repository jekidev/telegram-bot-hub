"""
Deploy all Valkyrie bots to Render as separate services.
"""
import os
import sys
import requests
from dataclasses import dataclass
from dotenv import load_dotenv

load_dotenv()

RENDER_API_BASE = "https://api.render.com/v1"
API_KEY = os.environ.get("RENDER_API_KEY", "")


@dataclass
class BotService:
    name: str
    start_command: str
    env_vars: list


BOT_SERVICES = [
    BotService("valkyrie-menu-bot", "python bots/menu_bot.py", ["VALKYRIEMENU_BOT_TOKEN", "GROK_API_KEY", "OPENROUTER_API_KEY"]),
    BotService("valkyrie-groupmod-bot", "python bots/group_guard_bot.py", ["VALKYRIEGROUPMOD_BOT_TOKEN", "DATABASE_URL"]),
    BotService("valkyrie-poster-bot", "python bots/llm_bridge_bot.py", ["VALKYRIEPOSTER1249_BOT_TOKEN", "GROK_API_KEY", "OPENROUTER_API_KEY"]),
    BotService("valkyrie-image-bot", "python bots/image_bot.py", ["VALKYRIEIMAGE_BOT_TOKEN", "GROK_API_KEY"]),
    BotService("valkyrie-welcome-bot", "python bots/lounge_bot.py", ["VALKYRIEWELCOME_BOT_TOKEN"]),
    BotService("valkyrie-cryptoauth-bot", "python bots/crypto_auth_bot.py", ["VALKYRIECRYPTOAUTH_BOT_TOKEN", "DATABASE_URL"]),
    BotService("valkyrie-socks5-bot", "python bots/socks5_bot.py", ["VALKYRIESOCKS5_BOT_TOKEN"]),
    BotService("valkyrie-sellerbuyer-bot", "python bots/seller_buyer_bot.py", ["VALKYRIESELLERBUYER_BOT_TOKEN", "DATABASE_URL", "BOT_ENCRYPTION_KEY"]),
]


def headers():
    return {
        "Authorization": f"Bearer {API_KEY}",
        "Accept": "application/json",
        "Content-Type": "application/json",
    }


def get_owner_id():
    resp = requests.get(f"{RENDER_API_BASE}/owners", headers=headers(), timeout=30)
    if resp.status_code == 200:
        data = resp.json()
        if data:
            return data[0].get("owner", data[0]).get("id")
    return None


def list_services():
    resp = requests.get(f"{RENDER_API_BASE}/services", headers=headers(), params={"limit": 100}, timeout=30)
    if resp.status_code == 200:
        data = resp.json()
        return [item.get("service", {}).get("name") for item in data if item.get("service")]
    return []


def create_service(service: BotService, owner_id: str):
    env_vars = [{"key": "PYTHON_VERSION", "value": "3.11.0"}, {"key": "PYTHONUNBUFFERED", "value": "1"}]
    for key in service.env_vars:
        value = os.environ.get(key, "")
        if value:
            env_vars.append({"key": key, "value": value})
    
    payload = {
        "type": "web_service",
        "name": service.name,
        "ownerId": owner_id,
        "runtime": "python",
        "plan": "starter",
        "region": "oregon",
        "buildCommand": "pip install -r requirements.txt",
        "startCommand": service.start_command,
        "autoDeploy": True,
    }
    
    resp = requests.post(f"{RENDER_API_BASE}/services", headers=headers(), json=payload, timeout=60)
    
    if resp.status_code == 201:
        data = resp.json()
        sid = data.get("service", {}).get("id") or data.get("id")
        print(f"✅ Created {service.name}: {sid}")
        
        for env in env_vars:
            try:
                requests.put(
                    f"{RENDER_API_BASE}/services/{sid}/env-vars/{env['key']}",
                    headers=headers(),
                    json={"value": env["value"]},
                    timeout=30,
                )
            except:
                pass
        return data
    else:
        print(f"❌ Failed {service.name}: {resp.status_code} {resp.text[:100]}")
        return None


def deploy_all():
    if not API_KEY:
        print("ERROR: RENDER_API_KEY not set")
        sys.exit(1)
    
    owner_id = get_owner_id()
    if not owner_id:
        print("ERROR: Could not get owner ID")
        sys.exit(1)
    print(f"Owner ID: {owner_id}")
    
    existing = list_services()
    print(f"Found {len(existing)} existing services")
    
    created = []
    for svc in BOT_SERVICES:
        if svc.name in existing:
            print(f"⏭️  {svc.name} exists, skipping")
            continue
        result = create_service(svc, owner_id)
        if result:
            created.append(svc.name)
    
    print(f"\n✅ Created {len(created)} services")
    for name in created:
        print(f"   - {name}")


if __name__ == "__main__":
    deploy_all()
