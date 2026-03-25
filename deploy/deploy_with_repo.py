"""
Alternative deployment using Render's service creation with repo.
"""
import os
import requests
from dotenv import load_dotenv

load_dotenv()

API_KEY = "rnd_rhDoNEAYIObZYXV0bf7BwDxbXec0"
BASE = "https://api.render.com/v1"


def headers():
    return {
        "Authorization": f"Bearer {API_KEY}",
        "Accept": "application/json",
        "Content-Type": "application/json",
    }


def get_owner():
    r = requests.get(f"{BASE}/owners", headers=headers(), timeout=30)
    if r.status_code == 200:
        data = r.json()
        if data:
            o = data[0].get("owner", data[0])
            return o.get("id"), o.get("type", "user")
    return None, None


def get_or_create_repo(owner_id: str):
    """Try to get an existing repo or we'll need to create one."""
    r = requests.get(f"{BASE}/repos", headers=headers(), timeout=30)
    if r.status_code == 200:
        repos = r.json()
        if repos:
            return repos[0].get("repo", {}).get("id")
    return None


def create_service_with_repo(owner_id: str, repo_id: str, name: str, start_cmd: str):
    # Build env vars from current environment
    env_vars = []
    if "DATABASE_URL" in os.environ:
        env_vars.append({"key": "DATABASE_URL", "value": os.environ["DATABASE_URL"]})
    if "BOT_ENCRYPTION_KEY" in os.environ:
        env_vars.append({"key": "BOT_ENCRYPTION_KEY", "value": os.environ["BOT_ENCRYPTION_KEY"]})
    for key in os.environ:
        if "TOKEN" in key or "API_KEY" in key:
            env_vars.append({"key": key, "value": os.environ[key]})
    
    payload = {
        "type": "web_service",
        "name": name,
        "ownerId": owner_id,
        "runtime": "python",
        "repoId": repo_id,
        "branch": "main",
        "plan": "starter",
        "region": "oregon",
        "buildCommand": "pip install -r requirements.txt",
        "startCommand": start_cmd,
        "autoDeploy": True,
    }
    
    r = requests.post(f"{BASE}/services", headers=headers(), json=payload, timeout=60)
    print(f"Create {name}: {r.status_code}")
    if r.status_code == 201:
        data = r.json()
        sid = data.get("service", {}).get("id") or data.get("id")
        
        # Set env vars
        for ev in env_vars:
            try:
                requests.put(
                    f"{BASE}/services/{sid}/env-vars/{ev['key']}",
                    headers=headers(),
                    json={"value": ev["value"]},
                    timeout=30,
                )
            except Exception as e:
                print(f"  env error: {e}")
        return sid
    else:
        print(f"  Error: {r.text[:200]}")
    return None


def deploy():
    print("Deploying to Render...")
    
    owner_id, owner_type = get_owner()
    if not owner_id:
        print("ERROR: No owner ID")
        return
    print(f"Owner: {owner_id} ({owner_type})")
    
    repo_id = get_or_create_repo(owner_id)
    if not repo_id:
        print("ERROR: No repos found. Please connect a GitHub repo in Render dashboard first.")
        print("\nManual steps:")
        print("1. Push this code to GitHub")
        print("2. Go to https://dashboard.render.com/")
        print("3. Click 'New +'")
        print("4. Select 'Blueprint'")
        print("5. Connect your GitHub repo")
        print("6. Render will create all services from render.yaml")
        return
    
    print(f"Using repo: {repo_id}")
    
    bots = [
        ("valkyrie-menu-bot", "python bots/menu_bot.py"),
        ("valkyrie-groupmod-bot", "python bots/group_guard_bot.py"),
        ("valkyrie-poster-bot", "python bots/llm_bridge_bot.py"),
        ("valkyrie-welcome-bot", "python bots/lounge_bot.py"),
        ("valkyrie-cryptoauth-bot", "python bots/crypto_auth_bot.py"),
        ("valkyrie-sellerbuyer-bot", "python bots/seller_buyer_bot.py"),
    ]
    
    created = []
    for name, cmd in bots:
        sid = create_service_with_repo(owner_id, repo_id, name, cmd)
        if sid:
            created.append(name)
        print()
    
    print(f"\n✅ Created {len(created)} services")


if __name__ == "__main__":
    deploy()
