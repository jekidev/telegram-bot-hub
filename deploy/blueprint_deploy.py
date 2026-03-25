"""
Deploy using Render Blueprint API (Infrastructure as Code).
This creates a blueprint instance from render.yaml
"""
import os
import json
import requests
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

API_KEY = os.environ.get("RENDER_API_KEY", "rnd_rhDoNEAYIObZYXV0bf7BwDxbXec0")
RENDER_API_BASE = "https://api.render.com/v1"


def get_headers():
    return {
        "Authorization": f"Bearer {API_KEY}",
        "Accept": "application/json",
        "Content-Type": "application/json",
    }


def get_owner_id():
    """Get the owner ID from Render API."""
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
                owner_id = owner.get("id") or owner.get("owner", {}).get("id")
                owner_type = owner.get("type") or owner.get("owner", {}).get("type", "user")
                return owner_id, owner_type
        print(f"Could not get owner: {resp.status_code}")
        return None, None
    except Exception as e:
        print(f"Error getting owner: {e}")
        return None, None


def list_blueprints():
    """List existing blueprints."""
    try:
        resp = requests.get(
            f"{RENDER_API_BASE}/blueprints",
            headers=get_headers(),
            timeout=30,
        )
        if resp.status_code == 200:
            data = resp.json()
            return data
        return []
    except Exception as e:
        print(f"Error listing blueprints: {e}")
        return []


def create_blueprint(owner_id: str):
    """Create a new blueprint from render.yaml."""
    # Read the render.yaml file
    render_yaml_path = Path("render.yaml")
    if not render_yaml_path.exists():
        print("ERROR: render.yaml not found")
        return None
    
    with open(render_yaml_path, "r") as f:
        blueprint_yaml = f.read()
    
    # Build payload according to Render API
    # Blueprint requires a repo - we'll create a "custom" blueprint
    payload = {
        "ownerId": owner_id,
        "name": "valkyrie-bots",
        "config": blueprint_yaml,
    }
    
    try:
        resp = requests.post(
            f"{RENDER_API_BASE}/blueprints",
            headers=get_headers(),
            json=payload,
            timeout=60,
        )
        print(f"Blueprint create response: {resp.status_code}")
        if resp.status_code in [200, 201]:
            data = resp.json()
            print(f"✅ Blueprint created: {data.get('id', 'unknown')}")
            return data
        else:
            print(f"❌ Failed to create blueprint: {resp.status_code}")
            print(f"Response: {resp.text}")
            return None
    except Exception as e:
        print(f"❌ Error creating blueprint: {e}")
        return None


def deploy_blueprint(blueprint_id: str):
    """Deploy services from a blueprint."""
    # This creates an "instance" of the blueprint
    try:
        resp = requests.post(
            f"{RENDER_API_BASE}/blueprints/{blueprint_id}/sync",
            headers=get_headers(),
            timeout=60,
        )
        if resp.status_code in [200, 201, 202]:
            print(f"✅ Blueprint sync initiated")
            return True
        else:
            print(f"⚠️ Blueprint sync: {resp.status_code} {resp.text}")
            return False
    except Exception as e:
        print(f"❌ Error syncing blueprint: {e}")
        return False


def main():
    print("🚀 Deploying Valkyrie Bots via Render Blueprint\n")
    
    # Get owner info
    owner_id, owner_type = get_owner_id()
    if not owner_id:
        print("ERROR: Could not get owner ID")
        return
    print(f"Owner: {owner_id} ({owner_type})\n")
    
    # Check existing blueprints
    print("Checking existing blueprints...")
    blueprints = list_blueprints()
    print(f"Found {len(blueprints)} blueprints\n")
    
    # Create new blueprint
    print("Creating blueprint from render.yaml...")
    blueprint = create_blueprint(owner_id)
    
    if blueprint:
        blueprint_id = blueprint.get("id")
        print(f"\nSyncing blueprint to create services...")
        deploy_blueprint(blueprint_id)
        print(f"\n✅ Deployment initiated!")
        print(f"📊 Check status at: https://dashboard.render.com/blueprints")
    else:
        print("\n⚠️ Using alternative approach...")
        print("\n" + "="*60)
        print("MANUAL DEPLOYMENT INSTRUCTIONS:")
        print("="*60)
        print("1. Go to https://dashboard.render.com/blueprints")
        print("2. Click 'New Blueprint Instance'")
        print("3. Connect your GitHub repository containing this project")
        print("4. Select 'Use existing blueprint'")
        print("5. Render will read render.yaml and create all 9 services")
        print("6. Set environment variables in the Render dashboard")
        print("="*60)


if __name__ == "__main__":
    main()
