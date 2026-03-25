"""
Create all bot services on Render using the API directly.
This creates each service individually with proper payload structure.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import requests
from dotenv import load_dotenv

load_dotenv()

API_KEY = os.environ.get("RENDER_API_KEY", "rnd_rhDoNEAYIObZYXV0bf7BwDxbXec0")
RENDER_API_BASE = "https://api.render.com/v1"


BOT_SERVICES = [
    {
        "name": "valkyrie-menu-bot",
        "start_command": "python bots/menu_bot.py",
        "env_vars": ["VALKYRIEMENU_BOT_TOKEN", "GROK_API_KEY", "OPENROUTER_API_KEY"],
    },
    {
        "name": "valkyrie-groupmod-bot",
        "start_command": "python bots/group_guard_bot.py",
        "env_vars": ["VALKYRIEGROUPMOD_BOT_TOKEN", "DATABASE_URL"],
    },
    {
        "name": "valkyrie-poster-bot",
        "start_command": "python bots/llm_bridge_bot.py",
        "env_vars": ["VALKYRIEPOSTER1249_BOT_TOKEN", "GROK_API_KEY", "OPENROUTER_API_KEY"],
    },
    {
        "name": "valkyrie-image-bot",
        "start_command": "python bots/image_bot.py",
        "env_vars": ["VALKYRIEIMAGE_BOT_TOKEN", "GROK_API_KEY"],
    },
    {
        "name": "valkyrie-welcome-bot",
        "start_command": "python bots/lounge_bot.py",
        "env_vars": ["VALKYRIEWELCOME_BOT_TOKEN"],
    },
    {
        "name": "valkyrie-cryptoauth-bot",
        "start_command": "python bots/crypto_auth_bot.py",
        "env_vars": ["VALKYRIECRYPTOAUTH_BOT_TOKEN", "DATABASE_URL"],
    },
    {
        "name": "valkyrie-socks5-bot",
        "start_command": "python bots/socks5_bot.py",
        "env_vars": ["VALKYRIESOCKS5_BOT_TOKEN"],
    },
    {
        "name": "valkyrie-sellerbuyer-bot",
        "start_command": "python bots/seller_buyer_bot.py",
        "env_vars": ["VALKYRIESELLERBUYER_BOT_TOKEN", "DATABASE_URL", "BOT_ENCRYPTION_KEY"],
    },
    {
        "name": "valkyrie-typebot-bot",
        "start_command": "python bots/typebot_bot.py",
        "env_vars": ["VALKYRIETYPEBOT_BOT_TOKEN", "TYPEBOT_VIEWER_URL"],
    },
]


def get_headers():
    return {
        "Authorization": f"Bearer {API_KEY}",
        "Accept": "application/json",
        "Content-Type": "application/json",
    }


def get_owner_id():
    """Get the owner ID (user ID) from Render API."""
    try:
        resp = requests.get(
            f"{RENDER_API_BASE}/owners",
            headers=get_headers(),
            timeout=30,
        )
        if resp.status_code == 200:
            data = resp.json()
            if isinstance(data, list) and len(data) > 0:
                owner = data[0]
                return owner.get("id") or owner.get("owner", {}).get("id")
        print(f"Could not get owner: {resp.status_code} {resp.text}")
        return None
    except Exception as e:
        print(f"Error getting owner: {e}")
        return None


def list_existing_services():
    """List all existing services."""
    try:
        resp = requests.get(
            f"{RENDER_API_BASE}/services",
            headers=get_headers(),
            params={"limit": 100},
            timeout=30,
        )
        if resp.status_code == 200:
            data = resp.json()
            services = []
            for item in data:
                svc = item.get("service", {})
                services.append(svc.get("name", ""))
            return services
        return []
    except Exception as e:
        print(f"Error listing services: {e}")
        return []


def create_service(owner_id: str, service: dict):
    """Create a new web service on Render."""
    name = service["name"]
    
    # Build env vars payload - only set the ones with actual values
    env_vars = [{"key": "PYTHON_VERSION", "value": "3.11.0"}]
    for env_key in service["env_vars"]:
        value = os.environ.get(env_key, "")
        if value:
            env_vars.append({"key": env_key, "value": value})
        else:
            # For empty env vars, still add them but as sync:false equivalent
            # Render API requires value or generateValue
            env_vars.append({"key": env_key, "value": "placeholder"})
    
    # Service payload structure per Render API
    payload = {
        "type": "web_service",
        "name": name,
        "ownerId": owner_id,
        "runtime": "python",
        "plan": "starter",  # Use starter (free equivalent)
        "region": "oregon",
        "branch": "main",
        "buildCommand": "pip install -r requirements.txt",
        "startCommand": service["start_command"],
        "autoDeploy": True,
    }
    
    try:
        resp = requests.post(
            f"{RENDER_API_BASE}/services",
            headers=get_headers(),
            json=payload,
            timeout=60,
        )
        
        if resp.status_code == 201:
            data = resp.json()
            service_id = data.get("id") or data.get("service", {}).get("id")
            print(f"✅ Created service: {name} ({service_id})")
            
            # Set env vars separately
            for env_var in env_vars:
                try:
                    env_resp = requests.put(
                        f"{RENDER_API_BASE}/services/{service_id}/env-vars/{env_var['key']}",
                        headers=get_headers(),
                        json={"value": env_var["value"]},
                        timeout=30,
                    )
                    if env_resp.status_code not in [200, 201]:
                        print(f"  ⚠️ Could not set {env_var['key']}: {env_resp.status_code}")
                except Exception as e:
                    print(f"  ⚠️ Error setting {env_var['key']}: {e}")
            
            return data
        else:
            print(f"❌ Failed to create {name}: {resp.status_code} {resp.text}")
            return None
    except Exception as e:
        print(f"❌ Error creating {name}: {e}")
        return None


def deploy_all():
    print("🚀 Deploying Valkyrie Bot Services to Render\n")
    
    if not API_KEY:
        print("ERROR: RENDER_API_KEY not set")
        sys.exit(1)
    
    # Get owner ID
    print("Getting owner ID...")
    owner_id = get_owner_id()
    if not owner_id:
        print("ERROR: Could not determine owner ID. Make sure your API key is valid.")
        sys.exit(1)
    print(f"Owner ID: {owner_id}\n")
    
    # Check existing services
    print("Checking existing services...")
    existing = list_existing_services()
    print(f"Found {len(existing)} existing services\n")
    
    # Create services
    created = []
    skipped = []
    failed = []
    
    print("Creating services...\n")
    for service in BOT_SERVICES:
        if service["name"] in existing:
            print(f"⏭️  {service['name']} already exists, skipping")
            skipped.append(service["name"])
            continue
        
        result = create_service(owner_id, service)
        if result:
            created.append(service["name"])
        else:
            failed.append(service["name"])
    
    # Summary
    print(f"\n{'='*50}")
    print(f"DEPLOYMENT SUMMARY")
    print(f"{'='*50}")
    print(f"✅ Created: {len(created)}")
    print(f"⏭️  Skipped: {len(skipped)} (already exist)")
    print(f"❌ Failed: {len(failed)}")
    
    if created:
        print(f"\n🌐 New services created:")
        for name in created:
            print(f"   - {name}")
        print(f"\nGo to https://dashboard.render.com/ to manage your services")
    
    if failed:
        print(f"\n❌ Failed services:")
        for name in failed:
            print(f"   - {name}")


if __name__ == "__main__":
    deploy_all()
