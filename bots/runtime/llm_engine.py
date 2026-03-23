import asyncio
import os
from pathlib import Path

import requests


BASE_DIR = Path(__file__).resolve().parent
SYSTEM_PROMPT_PATH = BASE_DIR / "llm_system_prompt.txt"

OLLAMA_KEY = os.environ.get("OLLAMA_STANDALONE_KEY", "")
OLLAMA_URL = os.environ.get("OLLAMA_BASE_URL", "")
VENICE_API_KEY = os.environ.get("OLLAMA_API_KEY", "")
VENICE_BASE_URL = "https://api.venice.ai/api/v1"
OPENROUTER_KEY = os.environ.get("OPENROUTER_API_KEY", "")
DISCORD_WEBHOOK = os.environ.get("DISCORD_WEBHOOK_URL", "")

TEMPERATURE = 0.95
MAX_TOKENS = 4096
HISTORY_LIMIT = 21

OLLAMA_MODELS = [
    "dolphin-mistral-24b-venice-edition",
    "llama3.3:70b",
    "mistral:latest",
]

VENICE_MODELS = [
    "dolphin-mistral-24b-venice-edition",
    "llama-3.3-70b",
    "mistral-31-24b",
]

OPENROUTER_MODELS = [
    "cognitivecomputations/dolphin-mistral-24b-venice-edition:free",
    "cognitivecomputations/dolphin3.0-mistral-24b:free",
    "nvidia/nemotron-3-super-120b-a12b:free",
    "stepfun/step-3.5-flash:free",
    "mistralai/mistral-small-3.1-24b-instruct:free",
]

POLLINATIONS_MODELS = ["openai", "mistral-large"]

_conversations = {}


def _read_system_prompt():
    prompt = os.environ.get("VALKYRIE_LLM_SYSTEM_PROMPT", "").strip()
    if prompt:
        return prompt

    if SYSTEM_PROMPT_PATH.exists():
        return SYSTEM_PROMPT_PATH.read_text(encoding="utf-8").strip()

    return "You are Valkyrie AI. Answer directly, clearly, and helpfully."


def clear_conversation(user_id):
    _conversations.pop(user_id, None)


def _build_messages(user_id, user_message):
    system_prompt = _read_system_prompt()
    if user_id not in _conversations:
        _conversations[user_id] = [{"role": "system", "content": system_prompt}]
    else:
        _conversations[user_id][0] = {"role": "system", "content": system_prompt}

    _conversations[user_id].append({"role": "user", "content": user_message})
    messages = _conversations[user_id][-HISTORY_LIMIT:]
    if messages[0]["role"] != "system":
        messages = [{"role": "system", "content": system_prompt}] + messages
    return messages


def _discord(message):
    if not DISCORD_WEBHOOK:
        return

    try:
        requests.post(DISCORD_WEBHOOK, json={"content": message}, timeout=10)
    except Exception:
        pass


def _post_json(url, headers, payload, timeout):
    response = requests.post(url, headers=headers, json=payload, timeout=timeout)
    if response.status_code in (404, 429, 503):
        return ""
    response.raise_for_status()
    return (response.json().get("choices", [{}])[0].get("message", {}).get("content") or "").strip()


def _try_ollama(messages):
    if not OLLAMA_KEY or not OLLAMA_URL:
        return ""

    base_url = OLLAMA_URL.rstrip("/")
    for model in OLLAMA_MODELS:
        try:
            reply = _post_json(
                f"{base_url}/v1/chat/completions",
                {"Authorization": f"Bearer {OLLAMA_KEY}", "Content-Type": "application/json"},
                {
                    "model": model,
                    "messages": messages,
                    "temperature": TEMPERATURE,
                    "max_tokens": MAX_TOKENS,
                },
                60,
            )
            if reply:
                return reply
        except Exception:
            continue
    return ""


def _try_venice(messages):
    if not VENICE_API_KEY:
        return ""

    for model in VENICE_MODELS:
        try:
            reply = _post_json(
                f"{VENICE_BASE_URL}/chat/completions",
                {"Authorization": f"Bearer {VENICE_API_KEY}", "Content-Type": "application/json"},
                {
                    "model": model,
                    "messages": messages,
                    "temperature": TEMPERATURE,
                    "max_tokens": MAX_TOKENS,
                    "venice_parameters": {"include_venice_system_prompt": False},
                },
                60,
            )
            if reply:
                return reply
        except Exception:
            continue
    return ""


def _try_openrouter(messages):
    if not OPENROUTER_KEY:
        return ""

    for model in OPENROUTER_MODELS:
        try:
            reply = _post_json(
                "https://openrouter.ai/api/v1/chat/completions",
                {
                    "Authorization": f"Bearer {OPENROUTER_KEY}",
                    "Content-Type": "application/json",
                    "HTTP-Referer": "https://valkyrie-cloud.onrender.com",
                    "X-Title": "Valkyrie AI",
                },
                {
                    "model": model,
                    "messages": messages,
                    "temperature": TEMPERATURE,
                    "max_tokens": MAX_TOKENS,
                },
                60,
            )
            if reply:
                return reply
        except Exception:
            continue
    return ""


def _try_pollinations(messages):
    for model in POLLINATIONS_MODELS:
        try:
            reply = _post_json(
                "https://text.pollinations.ai/openai",
                {"Content-Type": "application/json"},
                {
                    "model": model,
                    "messages": messages,
                    "temperature": TEMPERATURE,
                    "max_tokens": MAX_TOKENS,
                },
                45,
            )
            if reply:
                return reply
        except Exception:
            continue
    return ""


async def query_llm(user_id, user_message):
    messages = _build_messages(user_id, user_message)
    loop = asyncio.get_running_loop()

    reply = await loop.run_in_executor(None, _try_ollama, messages)
    if not reply:
        reply = await loop.run_in_executor(None, _try_venice, messages)
    if not reply:
        reply = await loop.run_in_executor(None, _try_openrouter, messages)
    if not reply:
        reply = await loop.run_in_executor(None, _try_pollinations, messages)
    if not reply:
        reply = "All AI providers are currently unreachable. Please try again shortly."
        _discord(f"All providers failed for user {user_id}.")

    _conversations.setdefault(user_id, [{"role": "system", "content": _read_system_prompt()}])
    _conversations[user_id].append({"role": "assistant", "content": reply})
    return reply
