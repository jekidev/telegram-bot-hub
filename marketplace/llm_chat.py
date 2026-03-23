"""
LLM Chat — tries providers in priority order, falls back automatically.

Priority:
  0. Valkyria LLM  (VALKYRIA_LLM_URL + VALKYRIA_LLM_KEY) — your own hosted model, always first
  1. Groq          (GROQ_API_KEY)         — fastest, very generous free tier
  2. Together      (TOGETHER_API_KEY)     — free credits
  3. OpenRouter    (OPENROUTER_API_KEY)   — free models available
  4. Mistral       (MISTRAL_API_KEY)      — free tier
  5. Cohere        (COHERE_API_KEY)       — free tier
  6. Gemini        (GEMINI_API_KEY / GOOGLE_API_KEY) — free tier
  7. Cerebras      (CEREBRAS_API_KEY)     — free tier
  8. Hugging Face  (HF_API_KEY optional) — free inference API
  9. Pollinations  (no key required)      — always-free REST endpoint
 10. DuckDuckGo   (no key required)      — unofficial free AI chat

Usage:
    from llm_chat import chat, clear_history
    reply = chat(session_id="user123", message="Hello!")
    clear_history("user123")
"""

import json
import logging
import os
import time
from collections import defaultdict

import requests

logger = logging.getLogger(__name__)

# ── Per-session conversation history ─────────────────────────────────────────
_history: dict[str, list[dict]] = defaultdict(list)
MAX_HISTORY = 20  # keep last 20 messages per session

SYSTEM_PROMPT = (
    "You are Valkyrie, the AI assistant for a Telegram marketplace bot. "
    "You help buyers and sellers with product requests, account questions, ratings, disputes, and general platform guidance. "
    "Be concise, friendly, and always in the same language the user writes in. "
    "If asked what you can do, explain the marketplace features: "
    "buyers can request products, rate sellers, view requests, join the lottery, and check their profile; "
    "sellers can list products, accept buyer requests, and build their rating. "
    "Never make up information about specific users, products, or transactions — only answer from context provided."
)


def _add_to_history(session_id: str, role: str, content: str):
    _history[session_id].append({"role": role, "content": content})
    if len(_history[session_id]) > MAX_HISTORY:
        _history[session_id] = _history[session_id][-MAX_HISTORY:]


def clear_history(session_id: str):
    _history[session_id] = []


def _get_messages(session_id: str, user_msg: str, system_override: str = None) -> list[dict]:
    msgs = [{"role": "system", "content": system_override or SYSTEM_PROMPT}]
    msgs.extend(_history[session_id])
    msgs.append({"role": "user", "content": user_msg})
    return msgs


# ── Individual provider functions ─────────────────────────────────────────────

def _openai_compat(url: str, api_key: str, model: str, messages: list[dict],
                   extra_headers: dict = None) -> str | None:
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    if extra_headers:
        headers.update(extra_headers)
    try:
        r = requests.post(url, headers=headers, json={
            "model": model,
            "messages": messages,
            "max_tokens": 512,
            "temperature": 0.7,
        }, timeout=20)
        if r.status_code == 200:
            return r.json()["choices"][0]["message"]["content"].strip()
        logger.debug(f"openai_compat {url} → {r.status_code}: {r.text[:200]}")
    except Exception as e:
        logger.debug(f"openai_compat {url} error: {e}")
    return None


def try_valkyria(messages: list[dict]) -> str | None:
    """Valkyria LLM — your own hosted model. Set VALKYRIA_LLM_URL and optionally VALKYRIA_LLM_KEY."""
    url = os.environ.get("VALKYRIA_LLM_URL", "").strip()
    if not url:
        return None
    key  = os.environ.get("VALKYRIA_LLM_KEY", "valkyria")
    model = os.environ.get("VALKYRIA_LLM_MODEL", "valkyria")
    return _openai_compat(url, key, model, messages)


def try_groq(messages: list[dict]) -> str | None:
    key = os.environ.get("GROQ_API_KEY")
    if not key:
        return None
    return _openai_compat(
        "https://api.groq.com/openai/v1/chat/completions",
        key, "llama-3.1-8b-instant", messages
    )


def try_together(messages: list[dict]) -> str | None:
    key = os.environ.get("TOGETHER_API_KEY")
    if not key:
        return None
    return _openai_compat(
        "https://api.together.xyz/v1/chat/completions",
        key, "meta-llama/Llama-3.2-11B-Vision-Instruct-Turbo", messages
    )


def try_openrouter(messages: list[dict]) -> str | None:
    key = os.environ.get("OPENROUTER_API_KEY")
    if not key:
        return None
    return _openai_compat(
        "https://openrouter.ai/api/v1/chat/completions",
        key, "mistralai/mistral-7b-instruct:free", messages,
        extra_headers={"HTTP-Referer": "https://marketplace-bot", "X-Title": "ValkyrieBot"}
    )


def try_mistral(messages: list[dict]) -> str | None:
    key = os.environ.get("MISTRAL_API_KEY")
    if not key:
        return None
    return _openai_compat(
        "https://api.mistral.ai/v1/chat/completions",
        key, "mistral-small-latest", messages
    )


def try_cohere(messages: list[dict]) -> str | None:
    key = os.environ.get("COHERE_API_KEY")
    if not key:
        return None
    try:
        chat_history = []
        for m in messages[1:]:  # skip system
            if m["role"] == "user":
                chat_history.append({"role": "USER", "message": m["content"]})
            elif m["role"] == "assistant":
                chat_history.append({"role": "CHATBOT", "message": m["content"]})
        user_msg = chat_history.pop()["message"] if chat_history else ""
        r = requests.post("https://api.cohere.ai/v1/chat", headers={
            "Authorization": f"Bearer {key}", "Content-Type": "application/json"
        }, json={
            "message": user_msg,
            "model": "command-r",
            "chat_history": chat_history,
            "preamble": SYSTEM_PROMPT,
        }, timeout=20)
        if r.status_code == 200:
            return r.json()["text"].strip()
    except Exception as e:
        logger.debug(f"Cohere error: {e}")
    return None


def try_gemini(messages: list[dict]) -> str | None:
    key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
    if not key:
        return None
    try:
        contents = []
        for m in messages[1:]:
            role = "user" if m["role"] == "user" else "model"
            contents.append({"role": role, "parts": [{"text": m["content"]}]})
        body = {
            "system_instruction": {"parts": [{"text": SYSTEM_PROMPT}]},
            "contents": contents,
            "generationConfig": {"maxOutputTokens": 512, "temperature": 0.7},
        }
        url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent?key={key}"
        r = requests.post(url, json=body, timeout=20)
        if r.status_code == 200:
            return r.json()["candidates"][0]["content"]["parts"][0]["text"].strip()
        logger.debug(f"Gemini → {r.status_code}: {r.text[:200]}")
    except Exception as e:
        logger.debug(f"Gemini error: {e}")
    return None


def try_cerebras(messages: list[dict]) -> str | None:
    key = os.environ.get("CEREBRAS_API_KEY")
    if not key:
        return None
    return _openai_compat(
        "https://api.cerebras.ai/v1/chat/completions",
        key, "llama3.1-8b", messages
    )


def try_huggingface(messages: list[dict]) -> str | None:
    key = os.environ.get("HF_API_KEY", "")
    headers = {"Content-Type": "application/json"}
    if key:
        headers["Authorization"] = f"Bearer {key}"
    prompt = "\n".join(
        f"{'User' if m['role']=='user' else 'Assistant'}: {m['content']}"
        for m in messages if m["role"] != "system"
    ) + "\nAssistant:"
    try:
        r = requests.post(
            "https://api-inference.huggingface.co/models/mistralai/Mistral-7B-Instruct-v0.3",
            headers=headers,
            json={"inputs": prompt, "parameters": {"max_new_tokens": 300, "return_full_text": False}},
            timeout=30,
        )
        if r.status_code == 200:
            result = r.json()
            if isinstance(result, list) and result:
                text = result[0].get("generated_text", "").strip()
                if text:
                    return text.split("User:")[0].strip()
        logger.debug(f"HuggingFace → {r.status_code}: {r.text[:200]}")
    except Exception as e:
        logger.debug(f"HuggingFace error: {e}")
    return None


def try_pollinations(messages: list[dict]) -> str | None:
    try:
        hdrs = {"User-Agent": "ValkyrieBot/1.0", "Content-Type": "application/json"}
        body = {"messages": messages, "model": "openai", "private": True}
        r = requests.post("https://text.pollinations.ai/", json=body, headers=hdrs, timeout=30)
        if r.status_code == 200 and r.text.strip():
            return r.text.strip()

        import urllib.parse
        prompt_parts = []
        for m in messages:
            if m["role"] == "system":
                prompt_parts.append(f"Instructions: {m['content']}")
            elif m["role"] == "user":
                prompt_parts.append(f"User: {m['content']}")
            else:
                prompt_parts.append(f"Assistant: {m['content']}")
        prompt = "\n".join(prompt_parts[-6:]) + "\nAssistant:"
        encoded = urllib.parse.quote(prompt[:1500])
        r2 = requests.get(
            f"https://text.pollinations.ai/{encoded}",
            timeout=30,
            headers={"User-Agent": "ValkyrieBot/1.0"},
        )
        if r2.status_code == 200 and r2.text.strip():
            return r2.text.strip()
        logger.debug(f"Pollinations → {r.status_code}")
    except Exception as e:
        logger.debug(f"Pollinations error: {e}")
    return None


def try_duckduckgo(messages: list[dict]) -> str | None:
    try:
        session = requests.Session()
        status_r = session.get(
            "https://duckduckgo.com/duckchat/v1/status",
            headers={"x-vqd-accept": "1"},
            timeout=10,
        )
        vqd = status_r.headers.get("x-vqd-4", "")
        if not vqd:
            return None
        payload_messages = [
            {"role": m["role"], "content": m["content"]}
            for m in messages if m["role"] != "system"
        ]
        r = session.post(
            "https://duckduckgo.com/duckchat/v1/chat",
            headers={
                "Content-Type": "application/json",
                "x-vqd-4": vqd,
                "User-Agent": "Mozilla/5.0",
            },
            json={"model": "gpt-4o-mini", "messages": payload_messages},
            stream=True,
            timeout=30,
        )
        if r.status_code != 200:
            return None
        full = []
        for line in r.iter_lines():
            if not line:
                continue
            text = line.decode() if isinstance(line, bytes) else line
            if text.startswith("data: "):
                data = text[6:]
                if data == "[DONE]":
                    break
                try:
                    chunk = json.loads(data)
                    full.append(chunk.get("message", ""))
                except json.JSONDecodeError:
                    pass
        result = "".join(full).strip()
        return result or None
    except Exception as e:
        logger.debug(f"DuckDuckGo error: {e}")
    return None


# ── Provider chain ─────────────────────────────────────────────────────────────

PROVIDERS = [
    ("Valkyria",     try_valkyria),
    ("Groq",         try_groq),
    ("Together",     try_together),
    ("OpenRouter",   try_openrouter),
    ("Mistral",      try_mistral),
    ("Cohere",       try_cohere),
    ("Gemini",       try_gemini),
    ("Cerebras",     try_cerebras),
    ("HuggingFace",  try_huggingface),
    ("Pollinations", try_pollinations),
    ("DuckDuckGo",   try_duckduckgo),
]


def chat(session_id: str, message: str, system_override: str = None) -> str:
    """
    Send a message in a session, maintain history, cascade through all providers.
    Returns the assistant reply, never raises.
    """
    messages = _get_messages(session_id, message, system_override)

    for attempt in range(2):
        for name, fn in PROVIDERS:
            try:
                reply = fn(messages)
                if reply:
                    logger.info(f"LLM reply via {name} (attempt {attempt+1})")
                    _add_to_history(session_id, "user", message)
                    _add_to_history(session_id, "assistant", reply)
                    return reply
            except Exception as e:
                logger.debug(f"{name} threw: {e}")
            time.sleep(0.2)

        if attempt == 0:
            logger.info("All providers returned None, retrying in 3s…")
            time.sleep(3)

    return "⚠️ All AI providers are temporarily busy. Please try again in a moment."


def chat_once(message: str, system_override: str = None) -> str:
    """Single-shot call with no history — useful for intent classification."""
    messages = [{"role": "system", "content": system_override or SYSTEM_PROMPT},
                {"role": "user",   "content": message}]
    for name, fn in PROVIDERS:
        try:
            reply = fn(messages)
            if reply:
                logger.info(f"chat_once via {name}")
                return reply
        except Exception as e:
            logger.debug(f"{name} threw: {e}")
        time.sleep(0.2)
    return ""
