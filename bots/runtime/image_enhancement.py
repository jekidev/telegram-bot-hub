import asyncio
import base64
import os
import random

import aiohttp
import requests
from io import BytesIO

from runtime.ai_keys import venice_api_key_candidates

DEEPAI_API_KEY = os.environ.get("DEEPAI_API_KEY", "quickstart-QUdJIGlzIGNvbWluZy4uLi4K")

VENICE_BASE_URL = "https://api.venice.ai/api/v1"
VENICE_VISION_MODELS = [
    m.strip()
    for m in os.environ.get(
        "VALKYRIE_VENICE_VISION_MODELS",
        "qwen3-vl-235b-a22b,qwen2.5-vl-72b",
    ).split(",")
    if m.strip()
]


async def _enhance_image_with_deepai(image_bytes: bytes) -> bytes | None:
    try:
        async with aiohttp.ClientSession() as session:
            form = aiohttp.FormData()
            form.add_field("image", image_bytes, filename="image.jpg", content_type="image/jpeg")
            headers = {"api-key": DEEPAI_API_KEY}
            async with session.post(
                "https://api.deepai.org/api/waifu2x",
                data=form,
                headers=headers,
                timeout=aiohttp.ClientTimeout(total=60),
            ) as resp:
                if resp.status != 200:
                    return None
                result = await resp.json()
                output_url = result.get("output_url")
                if not output_url:
                    return None
                async with session.get(output_url, timeout=aiohttp.ClientTimeout(total=60)) as img_resp:
                    if img_resp.status == 200:
                        return await img_resp.read()
    except Exception:
        return None
    return None


async def _enhance_image_simple(image_bytes: bytes) -> bytes | None:
    try:
        from PIL import Image, ImageEnhance, ImageFilter

        img = Image.open(BytesIO(image_bytes))
        img = img.resize((img.width * 2, img.height * 2), Image.LANCZOS)

        img = ImageEnhance.Sharpness(img).enhance(1.5)
        img = ImageEnhance.Contrast(img).enhance(1.1)
        img = ImageEnhance.Color(img).enhance(1.1)
        img = img.filter(ImageFilter.UnsharpMask(radius=1, percent=120, threshold=3))

        output = BytesIO()
        img.save(output, format="JPEG", quality=95)
        return output.getvalue()
    except Exception:
        return None


async def upscale_image(image_bytes: bytes) -> tuple[bytes | None, str]:
    result = await _enhance_image_with_deepai(image_bytes)
    if result:
        return result, "AI-upscaling med DeepAI (2x)"

    result = await _enhance_image_simple(image_bytes)
    if result:
        return result, "Lokalt upscaling (2x + skarphed + kontrast)"

    return None, "Fejl"


async def glow_up_image(image_bytes: bytes) -> tuple[bytes | None, str]:
    try:
        from PIL import Image, ImageEnhance, ImageFilter

        img = Image.open(BytesIO(image_bytes))
        img = img.resize((img.width * 2, img.height * 2), Image.LANCZOS)

        img = ImageEnhance.Color(img).enhance(1.3)
        img = ImageEnhance.Brightness(img).enhance(1.1)
        img = ImageEnhance.Contrast(img).enhance(1.15)
        img = ImageEnhance.Sharpness(img).enhance(1.8)
        img = img.filter(ImageFilter.UnsharpMask(radius=2, percent=150, threshold=3))

        output = BytesIO()
        img.save(output, format="JPEG", quality=95)
        return output.getvalue(), "Glow Up (2x + farver + lysstyrke + skarphed)"
    except Exception:
        return None, "Fejl"


def _venice_vision_roast_sync(image_bytes: bytes) -> str | None:
    """OpenAI-compatible vision roast via Venice; returns None on failure."""
    if not image_bytes:
        return None
    b64 = base64.standard_b64encode(image_bytes).decode("ascii")
    data_url = f"data:image/jpeg;base64,{b64}"
    prompt = (
        "Skriv en kort, sjov og lidt grov roast på dansk af personen på billedet. "
        "Maks 3 sætninger. Vær kreativ og hold det som vittighed."
    )
    for api_key in venice_api_key_candidates():
        for model in VENICE_VISION_MODELS:
            try:
                r = requests.post(
                    f"{VENICE_BASE_URL}/chat/completions",
                    headers={
                        "Authorization": f"Bearer {api_key}",
                        "Content-Type": "application/json",
                    },
                    json={
                        "model": model,
                        "messages": [
                            {
                                "role": "user",
                                "content": [
                                    {"type": "text", "text": prompt},
                                    {"type": "image_url", "image_url": {"url": data_url}},
                                ],
                            }
                        ],
                        "temperature": 0.9,
                        "max_tokens": 400,
                        "venice_parameters": {"include_venice_system_prompt": False},
                    },
                    timeout=90,
                )
                if r.status_code != 200:
                    continue
                data = r.json()
                text = (
                    (data.get("choices") or [{}])[0]
                    .get("message", {})
                    .get("content", "")
                    .strip()
                )
                if text:
                    return text
            except Exception:
                continue
    return None


async def roast_image_text(image_bytes: bytes) -> str:
    roasts = [
        "Du ser ud som om du ikke har sovet siden 2019.",
        "Er det et profilbillede eller et signal om hjælp?",
        "Filtrene på dit billede arbejder overarbejde.",
        "Din frisør skylder dig penge tilbage.",
        "Beklager, men vores AI nægtede at kigge på det her. Vi tvang den.",
        "Godt forsøg. Men LinkedIn ville heller ikke bruge det.",
        "Du er det modige valg for en catfish.",
        "Er det meningen at du ser søvnig ud, eller er det bare sådan du er?",
        "Du har den der 'jeg tager det seriøst' energi... men det gør ingen andre.",
    ]
    loop = asyncio.get_running_loop()
    ai_roast = await loop.run_in_executor(None, _venice_vision_roast_sync, image_bytes)
    if ai_roast:
        return ai_roast
    return random.choice(roasts)
