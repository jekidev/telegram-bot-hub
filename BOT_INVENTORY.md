# Valkyrie Bot Framework - Complete Inventory

## Bot Deployer Control Bot
- **Token**: `8685454358:AAF3uAkvzOaJqVVwuVPXd8CdLzC3CFXNtlI`
- **Username**: @valkyrietor_bot
- **Purpose**: Deploy/Stop all bots with Tor routing

---

## Framework Bots (telegram-bot-hub)

### 1. Menu Bot
- **Token**: `8768010386:AAFud_8Hh8rfZMSd2LaeD4MUads9wGlCyog`
- **Username**: @valkyriemenu_bot
- **Env Var**: `VALKYRIEMENU_BOT_TOKEN`
- **Purpose**: Main menu with bot links
- **File**: `bots/menu_bot.py`

### 2. Group Guard Bot
- **Token**: `8723211764:AAHO3ScorvF8GirZNKJG2co842LZzkU1rUo`
- **Username**: @valkyriegroupmod_bot
- **Env Var**: `VALKYRIEGROUPMOD_BOT_TOKEN`
- **Purpose**: Anti-raid, spam detection, media blocking
- **File**: `bots/group_guard_bot.py`

### 3. LLM Bridge Bot (Poster)
- **Token**: `8576982873:AAGchG0gYvgM82TtSJ7KF382PimRSQNyQG8`
- **Username**: @valkyrieposter1249_bot
- **Env Var**: `VALKYRIEPOSTER1249_BOT_TOKEN`
- **Purpose**: AI chat with LLM integration
- **File**: `bots/llm_bridge_bot.py`

### 4. Maigret OSINT Bot
- **Token**: (from VALKYRIEMOTHER_BOT_TOKEN)
- **Username**: @valkyriemother_bot
- **Env Var**: `VALKYRIEMOTHER_BOT_TOKEN`
- **Purpose**: Username/email/phone OSINT lookup
- **File**: `bots/maigret_bot.py`

### 5. Welcome/Lounge Bot
- **Token**: `8711330580:AAHFG49iux-f5MqIYpDGnLPPSBmeRYXxrv4`
- **Username**: @valkyriewelcome_bot
- **Env Var**: `VALKYRIEWELCOME_BOT_TOKEN`
- **Purpose**: Welcome messages, group games, polls
- **File**: `bots/welcome_bot.py`

### 6. Image Bot
- **Token**: `8606792990:AAH_VjejWrgzv_VDWVafcgw4p8w0NMy7DTK`
- **Username**: @valkyrieimagegen_bot
- **Env Var**: `VALKYRIEIMAGE_BOT_TOKEN`
- **Purpose**: Image upscale, glow-up, roast
- **File**: `bots/image_bot.py`
- **Source**: https://github.com/jekidev/Telegram-Image-Bot

### 8. Minimal LLM Bot
- **Token**: (not specified)
- **Username**: (not specified)
- **Purpose**: Minimal LLM interface
- **File**: `bots/minimal_llm_bot.py`

### 9. Typebot Bridge
- **Purpose**: Typebot.io integration
- **File**: `bots/typebot_bot.py`

### 10. CryptoAuth Bot
- **Token**: `8688831058:AAGqeTHxGGi5TiBpl9EocsyEe4RRz3zWxEQ`
- **Username**: @valkyriecryptoauth_bot
- **Env Var**: `VALKYRIECRYPTOAUTH_BOT_TOKEN`
- **Purpose**: Betalingsbaseret gruppeadgang med BTC/ETH/XMR
- **File**: `bots/crypto_auth_bot.py`
- **Features**: 
  - Manual admin godkendelse af betalinger
  - Wallet integration (BTC/ETH/XMR)
  - Captcha verifikation før adgang
  - Blacklist håndtering
  - Discord webhook notifikationer

---

## External Bots (Separate Projects)

### 10. Autoposting Bot (Valkyrie_POSTER035)
- **Location**: `menu_formatter_source/Menu-Formatter-Bot/valkyrie-poster035/`
- **Purpose**: Automated group posting with scheduler
- **Status**: ✅ Already has Tor support added

### 11. Telegram MCP Server
- **Location**: `telegram-mcp/`
- **Purpose**: Model Context Protocol for Telegram

---

## API Keys Used

### LLM APIs
- **Grok/xAI**: `xai-lsDGs7mj2dK5P3hbUCNOnbWGV`
- **OpenRouter**: `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`
- **Ollama/Venice**: `VENICE_ADMIN_KEY_f9H2Gt56gEf8OQGSaJIhho8gjAfLZJmMgEU8F4kZVT`
- **Base URL**: `https://api.venice.ai/api/v1`

### Admin Telegram API
- **API ID**: `33061958`
- **API Hash**: `ff34b762b2740f5308fe3ebf3d3592ff`
- **Phone**: `+45 6093 7504`
- **Telegram ID**: `8505253720`

### Webhooks
- **Discord Webhook**: `https://discord.com/api/webhooks/1484702499771383850/r4IouMfRoA5pOsRJj_-4pe8-02hCcfCblgcFVLxy1kuJyDlSQM1lDgDe2BSAA0zgG0rf`
- **Valkyrie Discord**: `https://discord.com/api/webhooks/1480729962607546440/86o-swZUFHNk2hC0JqVnGIiogWARQ9CkKBmOOw0i_hCZKn7ufa-coXCqr_1ygJvZvyO_`

### Session/Bridge
- **Session Secret**: `FW8V14djQQNbynvgZLEKByhdmwzor2EQ6kS6NrfBIn5MKyfhLPgwnYsWGDfFjuPLLbAh2fDo4JsNNaT3CQ5X2Q==`
- **Bridge API Key**: `tdPm5m92_bridge_api_key_7x9K3mNqL8vR2wP`
- **Bridge Port**: `5052`

### Database
- **URL**: `postgresql://valkyrie_db_1kxm_user:VX8QQqKZ6SEB1Z0j5pCuM4VmADvme5vU@dpg-d70rqvn5gffc739q7u50-a.oregon-postgres.render.com/valkyrie_db_1kxm`
- **Encryption Key**: `tdPm5m92!`

---

## Owner Information
- **Owner Chat ID**: `8505253720`
- **Owner Phone**: `+45 6093 7504`

---

## Files with VPN/Proxy References to Fix

1. ✅ `bots/grok_image_bot.py` - Has ProxyRotator class (31 proxy references)
2. ⏳ Check remaining bots for any proxy/VPN code

## Tor Configuration (To Add)

All bots should support:
```env
USE_TOR_PROXY=true
TOR_SOCKS5_PROXY=socks5://127.0.0.1:9050
```

---

*Generated: March 25, 2026*
