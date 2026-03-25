# Typebot.io Integration

This directory contains the Typebot.io chatbot platform integrated into the Telegram Bot Hub framework.

## Overview

Typebot is a visual chatbot builder that allows creating advanced conversational flows. This integration provides:

1. **Typebot Docker Services** (`typebot_service`) - Builder and Viewer containers
2. **Typebot Telegram Bot** (`typebot_bot`) - Telegram interface for Typebot chatbots

## Architecture

```
telegram-bot-hub/
├── typebot.io/           # Cloned Typebot repository (Docker services)
├── bots/
│   ├── typebot_bot.py    # Telegram bot wrapper
│   └── runtime/
│       └── typebot_service.py  # Docker service manager
└── bot_manager.py        # Updated with Typebot processes
```

## Services

### Typebot Builder (Port 8080)
- Admin interface for building chatbots
- URL: http://localhost:8080

### Typebot Viewer (Port 8081)
- Runtime for executing chatbot flows
- API endpoint for Telegram bot integration
- URL: http://localhost:8081

## Configuration

Add to your `.env` file:

```env
# Telegram Bot Token
VALKYRIETYPEBOT_BOT_TOKEN=your_bot_token_here

# Typebot Service Configuration
TYPEBOT_ENCRYPTION_SECRET=your_32_char_random_string
TYPEBOT_DATABASE_URL=postgresql://postgres:typebot@localhost:5432/typebot
TYPEBOT_NEXTAUTH_URL=http://localhost:8080
TYPEBOT_VIEWER_URL=http://localhost:8081
TYPEBOT_ADMIN_EMAIL=admin@yourdomain.com
DEFAULT_TYPEBOT_ID=your_default_typebot_id
```

## Usage

### Starting Typebot Services

Via Bot Manager:
```python
from bot_manager import BotManager
manager = BotManager()
manager.start("typebot_service")  # Start Docker containers
manager.start("typebot_bot")      # Start Telegram bot
```

Via CLI:
```bash
python bots/runtime/typebot_service.py start
python bots/typebot_bot.py
```

### Telegram Bot Commands

- `/start [typebot_id]` - Start a chatbot session
- `/session` - Show current session info
- `/reset` - Reset current session
- `/health` - Check Typebot service health

### Managing Services

```bash
# Check status
python bots/runtime/typebot_service.py status

# View logs
python bots/runtime/typebot_service.py logs

# Stop services
python bots/runtime/typebot_service.py stop
```

## Requirements

- Docker and Docker Compose installed
- Python 3.8+
- PostgreSQL (via Docker)
- Redis (via Docker)

## Integration Flow

1. User sends `/start <typebot_id>` to Telegram bot
2. Bot creates Typebot session via Viewer API
3. Typebot sends initial messages
4. User responses forwarded to Typebot
5. Typebot processes and returns next messages
6. Session continues until Typebot ends flow

## API Endpoints

- Viewer API: `http://localhost:8081/api/v1/`
- Start Chat: `POST /api/v1/typebots/{id}/startChat`
- Continue Chat: `POST /api/v1/sessions/{id}/continueChat`

## Notes

- Typebot requires a 32-character encryption secret
- Database persists in Docker volume `db-data`
- Services auto-restart on failure
- First startup may take 1-2 minutes for DB initialization
