import asyncio
import logging
import re

import aiofiles
import aiohttp
from bs4 import BeautifulSoup
from PIL import Image
from PIL.ExifTags import GPSTAGS, TAGS


logger = logging.getLogger(__name__)

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
}

SOCIAL_DOMAINS = [
    "instagram.com",
    "facebook.com",
    "tiktok.com",
    "twitter.com",
    "x.com",
    "linkedin.com",
    "vk.com",
    "snapchat.com",
    "reddit.com",
    "youtube.com",
    "pinterest.com",
    "tumblr.com",
    "flickr.com",
]


def extract_exif(image_path):
    result = {
        "camera": None,
        "software": None,
        "datetime": None,
        "gps": None,
        "map_link": None,
        "dimensions": None,
        "raw": {},
    }

    try:
        image = Image.open(image_path)
        result["dimensions"] = f"{image.width}x{image.height}px"
        exif_data = image._getexif()
        if not exif_data:
            return result

        decoded = {}
        for tag_id, value in exif_data.items():
            decoded[TAGS.get(tag_id, str(tag_id))] = value
        result["raw"] = decoded

        make = decoded.get("Make", "")
        model = decoded.get("Model", "")
        if make or model:
            result["camera"] = f"{make} {model}".strip()
        result["software"] = decoded.get("Software")
        result["datetime"] = decoded.get("DateTimeOriginal") or decoded.get("DateTime")

        gps_info = decoded.get("GPSInfo")
        if gps_info:
            gps_decoded = {}
            for key, value in gps_info.items():
                gps_decoded[GPSTAGS.get(key, key)] = value
            lat = _convert_gps(gps_decoded.get("GPSLatitude"), gps_decoded.get("GPSLatitudeRef", "N"))
            lon = _convert_gps(gps_decoded.get("GPSLongitude"), gps_decoded.get("GPSLongitudeRef", "E"))
            if lat is not None and lon is not None:
                result["gps"] = (round(lat, 6), round(lon, 6))
                result["map_link"] = f"https://www.google.com/maps?q={lat},{lon}"
    except Exception as exc:
        logger.warning("EXIF extraction error: %s", exc)

    return result


def _convert_gps(coord, ref):
    if not coord:
        return None
    try:
        def to_float(value):
            if isinstance(value, tuple):
                return value[0] / value[1] if value[1] else 0.0
            return float(value)

        degrees, minutes, seconds = [to_float(value) for value in coord]
        decimal = degrees + minutes / 60.0 + seconds / 3600.0
        if ref in ("S", "W"):
            decimal = -decimal
        return decimal
    except Exception:
        return None


async def yandex_reverse_search(image_path):
    links = []
    try:
        async with aiofiles.open(image_path, "rb") as file_obj:
            image_bytes = await file_obj.read()

        form_data = aiohttp.FormData()
        form_data.add_field(
            "upfile",
            image_bytes,
            filename="image.jpg",
            content_type="image/jpeg",
        )

        async with aiohttp.ClientSession(headers=HEADERS) as session:
            async with session.post(
                "https://yandex.com/images/search",
                data=form_data,
                params={
                    "rpt": "imageview",
                    "format": "json",
                    "request": '{"blocks":[{"block":"b-page_type_search-by-image__link"}]}',
                },
                timeout=aiohttp.ClientTimeout(total=20),
                allow_redirects=True,
            ) as response:
                html = await response.text(errors="ignore")

        soup = BeautifulSoup(html, "html.parser")
        for anchor in soup.find_all("a", href=True):
            href = anchor["href"]
            if href.startswith("http") and len(href) > 15:
                links.append(href)
        for meta in soup.find_all("meta", property=True):
            content = meta.get("content", "")
            if "url" in meta.get("property", "") and content.startswith("http"):
                links.append(content)
    except Exception as exc:
        logger.warning("Yandex reverse search error: %s", exc)

    return list(dict.fromkeys(links))


def extract_social_links(links):
    return list(dict.fromkeys([link for link in links if any(domain in link for domain in SOCIAL_DOMAINS)]))[:20]


def extract_usernames_from_links(links):
    usernames = []
    patterns = [
        r"instagram\.com/([A-Za-z0-9_.]+)",
        r"facebook\.com/([A-Za-z0-9_.]+)",
        r"tiktok\.com/@([A-Za-z0-9_.]+)",
        r"twitter\.com/([A-Za-z0-9_]+)",
        r"x\.com/([A-Za-z0-9_]+)",
    ]
    for link in links:
        for pattern in patterns:
            match = re.search(pattern, link)
            if match:
                username = match.group(1)
                if username not in {"p", "reel", "stories", "explore", "search", "share"}:
                    usernames.append(username)
    return list(dict.fromkeys(usernames))


def analyze_visual_scene(image_path):
    clues = []
    env_type = "unknown"
    try:
        image = Image.open(image_path).convert("RGB")
        small = image.resize((200, 200))
        pixels = list(small.getdata())
        r_vals = [pixel[0] for pixel in pixels]
        g_vals = [pixel[1] for pixel in pixels]
        b_vals = [pixel[2] for pixel in pixels]
        avg_brightness = sum(r_vals + g_vals + b_vals) / (3 * len(pixels))
        r_mean = sum(r_vals) / len(r_vals)
        g_mean = sum(g_vals) / len(g_vals)
        b_mean = sum(b_vals) / len(b_vals)

        import statistics

        r_var = statistics.variance(r_vals[:500])

        if r_mean > 150 and g_mean > 120 and b_mean < 100:
            clues.append("Yellow or warm tones suggest parking, taxi, or warning areas.")
            env_type = "parking/taxi/indoor"
        if avg_brightness < 80:
            clues.append("Low light suggests an underground, enclosed, or night scene.")
            env_type = "underground/night"
        if avg_brightness > 160 and r_var < 800:
            clues.append("Bright uniform surfaces suggest an elevator, corridor, or indoor space.")
            env_type = "indoor/elevator"
        if avg_brightness > 100 and r_var > 2000:
            clues.append("High visual complexity suggests an outdoor urban environment.")
            env_type = "outdoor/urban"
        grey_score = 1 - (abs(r_mean - g_mean) + abs(g_mean - b_mean)) / 255
        if grey_score > 0.92 and avg_brightness > 80:
            clues.append("Grey-dominant scene suggests concrete, parking, or industrial surroundings.")
            env_type = "parking/industrial"
    except Exception:
        pass

    return {"clues": clues, "env_type": env_type}


def build_geo_estimate(exif, scene, user_context):
    lines = []
    if exif.get("gps"):
        lat, lon = exif["gps"]
        lines.append(f"GPS confirmed: {lat}, {lon}")
        lines.append(f"Map: {exif['map_link']}")
        return "\n".join(lines)

    ctx = user_context.strip().lower() if user_context else ""
    city_hints = []
    dk_cities = {
        "kobenhavn": "Copenhagen, Denmark",
        "aarhus": "Aarhus, Denmark",
        "odense": "Odense, Denmark",
        "aalborg": "Aalborg, Denmark",
        "esbjerg": "Esbjerg, Denmark",
        "randers": "Randers, Denmark",
        "kolding": "Kolding, Denmark",
        "horsens": "Horsens, Denmark",
        "vejle": "Vejle, Denmark",
        "roskilde": "Roskilde, Denmark",
    }

    for key, full_name in dk_cities.items():
        if key in ctx:
            city_hints.append(full_name)

    scene_clues = scene.get("clues", [])
    env_type = scene.get("env_type", "unknown")

    lines.append("GEO ESTIMATE (no GPS in image):")
    if city_hints:
        lines.append(f"City context: {', '.join(city_hints)}")
    if scene_clues:
        lines.append("Visual clues:")
        for clue in scene_clues:
            lines.append(f"- {clue}")

    if city_hints and env_type != "unknown":
        env_map = {
            "parking/taxi/indoor": "parking garage or taxi rank",
            "underground/night": "underground car park or night scene",
            "indoor/elevator": "elevator or building interior",
            "outdoor/urban": "urban street or square",
            "parking/industrial": "concrete parking structure or industrial area",
        }
        lines.append(f"Estimate: {city_hints[0]} - {env_map.get(env_type, 'indoor location')}")
    elif city_hints:
        lines.append(f"Estimate: {city_hints[0]} (location type unclear from image)")
    elif env_type != "unknown":
        lines.append(f"Estimate: location type detected - {env_type} (city unknown)")
    else:
        lines.append("Estimate: insufficient data for location estimation")

    if ctx and not city_hints:
        lines.append(f'User context: "{user_context.strip()}"')

    return "\n".join(lines)


async def run_image_search(image_path, user_context=""):
    lines = ["VALKYRIE IMAGE OSINT REPORT", ""]

    loop = asyncio.get_running_loop()
    exif = await loop.run_in_executor(None, extract_exif, image_path)
    scene = await loop.run_in_executor(None, analyze_visual_scene, image_path)

    lines.append("IMAGE INFO:")
    if exif["dimensions"]:
        lines.append(f"Resolution: {exif['dimensions']}")
    if exif["camera"]:
        lines.append(f"Device: {exif['camera']}")
    if exif["software"]:
        lines.append(f"Software: {exif['software']}")
    if exif["datetime"]:
        lines.append(f"Taken: {exif['datetime']}")
    if not any([exif["camera"], exif["datetime"], exif["gps"]]):
        lines.append("No metadata found. The image may have been re-shared via social media.")

    notable = ["Make", "Model", "FocalLength", "ExposureTime", "ISOSpeedRatings", "Flash"]
    extras = [(key, str(exif["raw"].get(key, ""))) for key in notable if exif["raw"].get(key)]
    if extras:
        lines.extend(["", "CAMERA DETAILS:"])
        for key, value in extras[:5]:
            lines.append(f"{key}: {value}")

    lines.extend(["", build_geo_estimate(exif, scene, user_context)])

    yandex_links = await yandex_reverse_search(image_path)
    social_links = extract_social_links(yandex_links)
    usernames = extract_usernames_from_links(yandex_links)

    lines.extend(["", "REVERSE IMAGE SEARCH:"])
    if social_links:
        lines.append(f"Hits found: {len(social_links)}")
        for link in social_links[:8]:
            lines.append(f"- {link}")
    else:
        lines.append("No reverse-image hits found.")

    if usernames:
        lines.extend(["", f"Usernames found ({len(usernames)}):"])
        for username in usernames[:6]:
            lines.append(f"- @{username}")

    score = 0
    if exif["gps"]:
        score += 40
    if exif["camera"]:
        score += 15
    if exif["datetime"]:
        score += 10
    if scene["clues"]:
        score += 10
    if user_context and user_context.lower() != "skip":
        score += 5
    if social_links:
        score += min(len(social_links) * 8, 25)
    if usernames:
        score += min(len(usernames) * 5, 15)
    score = min(score, 100)

    confidence = "HIGH" if score >= 70 else ("MEDIUM" if score >= 35 else "LOW")
    lines.extend(["", f"Identity Score: {score}/100 {confidence}"])
    return "\n".join(lines)
