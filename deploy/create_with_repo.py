"""
Create Render services using the correct API endpoint structure.
Requires creating services with git repo reference.
"""
import os
import json
import requests
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

API_KEY = "rnd_rhDoNEAYIObZYXV0bf7BwDxbXec0"
RENDER_API_BASE = "https://api.render.com/v1"


def get_headers():
    return {
        "Authorization": f"Bearer {API_KEY}",
        "Accept": "application/json",
        "Content-Type": "application/json",
    }


def get_owner():
    """Get owner info."""
    resp = requests.get(f"{RENDER_API_BASE}/owners", headers=get_headers(), timeout=30)
    if resp.status_code == 200:
        data = resp.json()
        if data:
            owner = data[0].get("owner", data[0])
            return owner.get("id"), owner.get("type", "user")
    return None, None


def create_service_direct(owner_id: str, name: str, start_cmd: str):
    """Create a web service with minimal config."""
    
    # Render API requires a repo. Let's check if there's a repo ID we can use
    # First, let's list any existing repos
    resp = requests.get(
        f"{RENDER_API_BASE}/repos",
        headers=get_headers(),
        timeout=30,
    )
    
    if resp.status_code == 200:
        repos = resp.json()
        if repos and len(repos) > 0:
            repo_id = repos[0].get("repo", {}).get("id")
            print(f"Using repo: {repo_id}")
        else:
            print("No repos found. Creating services requires a connected Git repository.")
            print("Please connect a GitHub/GitLab repo to Render first.")
            return None
    else:
        print(f"Could not list repos: {resp.status_code}")
        return None
    
    # Build proper payload for web service creation
    payload = {
        "type": "web_service",
        "name": name,
        "ownerId": owner_id,
        "runtime": "python",
        "plan": "starter",
        "region": "oregon",
        "repoId": repo_id,
        "branch": "main",
        "buildCommand": "pip install -r requirements.txt",
        "startCommand": start_cmd,
        "autoDeploy": True,
    }
    
    resp = requests.post(
        f"{RENDER_API_BASE}/services",
        headers=get_headers(),
        json=payload,
        timeout=60,
    )
    
    print(f"Create service response: {resp.status_code}")
    if resp.status_code in [200, 201]:
        data = resp.json()
        service_id = data.get("service", {}).get("id") or data.get("id")
        print(f"✅ Created {name}: {service_id}")
        return data
    else:
        print(f"❌ Failed: {resp.text[:200]}")
        return None


def main():
    print("🔧 Render Service Creator\n")
    
    owner_id, owner_type = get_owner()
    if not owner_id:
        print("ERROR: Could not get owner ID")
        return
    
    print(f"Owner: {owner_id} ({owner_type})\n")
    
    # Try to create one service as a test
    print("Attempting to create test service...")
    result = create_service_direct(owner_id, "valkyrie-menu-bot", "python bots/menu_bot.py")
    
    if result:
        print("\n✅ Success! Service created.")
        print("Now you can:")
        print("1. Go to https://dashboard.render.com/")
        print("2. Find your new service")
        print("3. Set environment variables")
        print("4. Deploy remaining bots using the same pattern")
    else:
        print("\n⚠️ Service creation requires a Git repository connection.")
        print("\nRECOMMENDED DEPLOYMENT METHOD:")
        print("1. Push this project to GitHub")
        print("2. Go to https://dashboard.render.com/blueprints")
        print("3. Click 'New Blueprint Instance'")
        print("4. Connect your GitHub repo")
        print("5. Render will automatically create all services from render.yaml")


if __name__ == "__main__":
    main()
