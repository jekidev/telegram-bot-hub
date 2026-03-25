"""
Deploy all Valkyrie bots to Render as separate services.
Uses blueprints for proper deployment.
"""
from __future__ import annotations

import os
import sys
import subprocess
from pathlib import Path
from dataclasses import dataclass, asdict
import yaml

# Load environment variables
from dotenv import load_dotenv
load_dotenv()


@dataclass
class BotService:
    name: str
    start_command: str
    env_vars: list[str]
    plan: str = "free"
    health_check: str = "/health"


# Define all bot services to deploy
BOT_SERVICES = [
    BotService(
        name="valkyrie-menu-bot",
        start_command="python bots/menu_bot.py",
        env_vars=["VALKYRIEMENU_BOT_TOKEN", "GROK_API_KEY", "OPENROUTER_API_KEY"],
    ),
    BotService(
        name="valkyrie-groupmod-bot",
        start_command="python bots/group_guard_bot.py",
        env_vars=["VALKYRIEGROUPMOD_BOT_TOKEN", "DATABASE_URL"],
    ),
    BotService(
        name="valkyrie-poster-bot",
        start_command="python bots/llm_bridge_bot.py",
        env_vars=["VALKYRIEPOSTER1249_BOT_TOKEN", "GROK_API_KEY", "OPENROUTER_API_KEY"],
    ),
    BotService(
        name="valkyrie-image-bot",
        start_command="python bots/image_bot.py",
        env_vars=["VALKYRIEIMAGE_BOT_TOKEN", "GROK_API_KEY"],
    ),
    BotService(
        name="valkyrie-welcome-bot",
        start_command="python bots/lounge_bot.py",
        env_vars=["VALKYRIEWELCOME_BOT_TOKEN"],
    ),
    BotService(
        name="valkyrie-cryptoauth-bot",
        start_command="python bots/crypto_auth_bot.py",
        env_vars=["VALKYRIECRYPTOAUTH_BOT_TOKEN", "DATABASE_URL"],
    ),
    BotService(
        name="valkyrie-socks5-bot",
        start_command="python bots/socks5_bot.py",
        env_vars=["VALKYRIESOCKS5_BOT_TOKEN"],
    ),
    BotService(
        name="valkyrie-sellerbuyer-bot",
        start_command="python bots/seller_buyer_bot.py",
        env_vars=["VALKYRIESELLERBUYER_BOT_TOKEN", "DATABASE_URL", "BOT_ENCRYPTION_KEY"],
    ),
    BotService(
        name="valkyrie-typebot-bot",
        start_command="python bots/typebot_bot.py",
        env_vars=["VALKYRIETYPEBOT_BOT_TOKEN", "TYPEBOT_VIEWER_URL"],
    ),
]


def generate_render_yaml():
    """Generate a complete render.yaml with all bot services."""
    services = []
    
    for bot in BOT_SERVICES:
        # Build env var list
        env_vars = [{"key": "PYTHON_VERSION", "value": "3.11.0"}]
        for env_key in bot.env_vars:
            env_vars.append({"key": env_key, "sync": False})
        
        service = {
            "type": "web",
            "name": bot.name,
            "runtime": "python",
            "plan": bot.plan,
            "buildCommand": "pip install -r requirements.txt",
            "startCommand": bot.start_command,
            "healthCheckPath": bot.health_check,
            "envVars": env_vars,
            "autoDeploy": True,
        }
        services.append(service)
    
    render_config = {"services": services}
    return render_config


def save_render_yaml():
    """Save the render.yaml file."""
    config = generate_render_yaml()
    yaml_path = Path("render.yaml")
    
    with open(yaml_path, "w") as f:
        yaml.dump(config, f, default_flow_style=False, sort_keys=False)
    
    print(f"✅ Generated {yaml_path} with {len(config['services'])} services")
    return yaml_path


def create_blueprint_instance():
    """Create a blueprint instance via Render CLI or API."""
    print("\n📋 To deploy all bots:")
    print("1. Commit the updated render.yaml")
    print("2. Go to https://dashboard.render.com/blueprints")
    print("3. Click 'New Blueprint'")
    print("4. Connect your GitHub repo")
    print("5. Render will create all services automatically\n")
    
    # Alternative: deploy via CLI if available
    try:
        result = subprocess.run(
            ["render", "blueprint", "create", "--file", "render.yaml"],
            capture_output=True,
            text=True,
            cwd="."
        )
        if result.returncode == 0:
            print("✅ Blueprint created successfully!")
            print(result.stdout)
        else:
            print(f"ℹ️ CLI output: {result.stderr}")
    except FileNotFoundError:
        print("ℹ️ Render CLI not installed. Use web dashboard instead.")


def main():
    print("🚀 Generating Render deployment configuration...\n")
    
    # Generate and save render.yaml
    yaml_path = save_render_yaml()
    
    # Show preview
    with open(yaml_path) as f:
        print("📄 render.yaml contents:\n")
        print(f.read())
    
    # Instructions for deployment
    create_blueprint_instance()
    
    print(f"\n🌐 After deployment, your bots will be available at:")
    for bot in BOT_SERVICES:
        print(f"   - {bot.name}: https://{bot.name}.onrender.com")


if __name__ == "__main__":
    main()
