import asyncio
import logging
import re
import shutil
import subprocess

import aiohttp
from bs4 import BeautifulSoup


logger = logging.getLogger(__name__)

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "da-DK,da;q=0.9,en;q=0.8",
}

USERNAME_SITES_VERIFIED = {
    "GitHub": ("https://github.com/{}", []),
    "Reddit": ("https://reddit.com/user/{}", []),
    "Dev.to": ("https://dev.to/{}", ["404", "not found"]),
    "Behance": (
        "https://behance.net/{}",
        ["page not found", "doesn't exist", "this page does not exist"],
    ),
    "Twitch": ("https://twitch.tv/{}", []),
    "Steam": ("https://steamcommunity.com/id/{}", ["error"]),
    "Vimeo": (
        "https://vimeo.com/{}",
        ["sorry, we couldn't find that page", "page not found"],
    ),
    "Flickr": (
        "https://flickr.com/people/{}",
        ["page not found", "nobody here but us chickens"],
    ),
}

USERNAME_SITES_MANUAL = {
    "Twitter/X": "https://twitter.com/{}",
    "Instagram": "https://instagram.com/{}",
    "TikTok": "https://tiktok.com/@{}",
    "LinkedIn": "https://linkedin.com/in/{}",
    "YouTube": "https://youtube.com/@{}",
    "Medium": "https://medium.com/@{}",
    "Snapchat": "https://www.snapchat.com/add/{}",
    "Patreon": "https://patreon.com/{}",
    "Pornhub": "https://www.pornhub.com/users/{}",
    "XVideos": "https://www.xvideos.com/profiles/{}",
    "OnlyFans": "https://onlyfans.com/{}",
    "Chaturbate": "https://chaturbate.com/{}",
    "Fansly": "https://fansly.com/{}",
    "Stripchat": "https://stripchat.com/{}",
    "RedTube": "https://www.redtube.com/users/{}",
}

DK_DIRECTORIES = {
    "Krak": "https://www.krak.dk/soeg?q={phone}",
    "DeGuleSider": "https://www.degulesider.dk/resultater?q={phone}",
    "118.dk": "https://118.dk/resultater?q={phone}",
    "FindPerson": "https://find-person.dk/soeg?q={phone}",
}

HOLEHE_BIN = shutil.which("holehe") or "/home/runner/workspace/.pythonlibs/bin/holehe"
MAIGRET_BIN = shutil.which("maigret") or "/home/runner/workspace/.pythonlibs/bin/maigret"


def normalize_phone(phone):
    clean = re.sub(r"[^\d+]", "", phone)
    if clean.startswith("0045"):
        clean = clean[4:]
    elif clean.startswith("00"):
        clean = clean[2:]
    if clean.startswith("45") and len(clean) == 10:
        clean = clean[2:]
    short = clean.lstrip("+").lstrip("45")[-8:] if len(clean) >= 8 else clean
    intl = f"+45{short}" if not clean.startswith("+") else phone
    return intl, short


def _extract_persons_from_text(text):
    persons = []

    addr_full_re = re.compile(
        r"([A-ZA-Z][A-Za-z\s\-]{2,35}\d+\s*[A-Za-z]?(?:[,\s]+)(\d{4})\s+([A-Za-z][A-Za-z\s\-]{2,25}))"
    )
    name_re = re.compile(r"\b([A-Z][a-z]{1,20}(?:\s+[A-Z][a-z]{1,20}){1,3})\b")
    age_re = re.compile(r"\b(\d{2})\s*ar\b|\bf(?:odt|od)\.?\s*(\d{4})\b", re.IGNORECASE)
    email_re = re.compile(r"\b[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}\b")

    noise = {
        "Sog",
        "Krak",
        "Find",
        "Side",
        "Klik",
        "Vis",
        "Alle",
        "Mere",
        "Privat",
        "Person",
        "Telefon",
        "Adresse",
        "Resultat",
    }

    for match in addr_full_re.finditer(text):
        full_addr = match.group(0).strip()
        postal = match.group(2)
        city = match.group(3).strip()
        start = max(0, match.start() - 200)
        context = text[start:match.end()]

        names_nearby = [name for name in name_re.findall(context) if name.split()[0] not in noise]

        age_match = age_re.search(context)
        age = ""
        if age_match:
            age = f"{age_match.group(1)} ar" if age_match.group(1) else f"f. {age_match.group(2)}"

        email_match = email_re.search(context)
        email = email_match.group(0) if email_match else ""

        persons.append(
            {
                "name": names_nearby[-1] if names_nearby else "",
                "street": full_addr,
                "postal": postal,
                "city": city,
                "age": age,
                "email": email,
            }
        )

    return persons[:4]


async def _scrape_directory(session, name, url):
    try:
        async with session.get(
            url,
            timeout=aiohttp.ClientTimeout(total=14),
            allow_redirects=True,
        ) as response:
            html = await response.text(errors="ignore")
            soup = BeautifulSoup(html, "html.parser")

        persons = []
        selectors = [
            ".vcard, [class*='hit'], [class*='person-result'], [class*='search-result'], [class*='result-item'], article",
            "[class*='result'], [class*='person'], [class*='hit'], li, .card",
            "[class*='result'], [class*='person'], [class*='entry'], article, li",
        ]

        for selector in selectors:
            for card in soup.select(selector)[:5]:
                persons.extend(_extract_persons_from_text(card.get_text(" ", strip=True)))
            if persons:
                break

        if not persons:
            persons = _extract_persons_from_text(soup.get_text(" ", strip=True))

        seen = set()
        unique = []
        for person in persons:
            street = person.get("street", "")
            if street and street not in seen:
                seen.add(street)
                unique.append(person)

        bare_names = []
        if not unique:
            full_text = soup.get_text(" ", strip=True)
            bare_names = list(
                set(re.findall(r"\b([A-Z][a-z]{2,20}\s+[A-Z][a-z]{2,20})\b", full_text))
            )[:4]

        return {
            "source": name,
            "url": url,
            "found": bool(unique or bare_names),
            "persons": unique,
            "names": bare_names,
        }
    except Exception as exc:
        return {
            "source": name,
            "url": url,
            "found": False,
            "persons": [],
            "names": [],
            "error": str(exc),
        }


async def search_phone(phone):
    intl, short = normalize_phone(phone)
    results = {
        "type": "phone",
        "query": intl,
        "directories": {},
        "social_links": {
            "WhatsApp": f"https://wa.me/45{short}",
            "Telegram": f"https://t.me/+45{short}",
            "Signal": f"https://signal.me/#p/+45{short}",
        },
    }

    async with aiohttp.ClientSession(headers=HEADERS) as session:
        tasks = [
            _scrape_directory(session, name, url_tpl.format(phone=short))
            for name, url_tpl in DK_DIRECTORIES.items()
        ]
        for result in await asyncio.gather(*tasks, return_exceptions=True):
            if isinstance(result, dict):
                results["directories"][result["source"]] = result

    return results


async def _check_site_verified(session, site, url, not_found_patterns):
    try:
        async with session.get(
            url,
            timeout=aiohttp.ClientTimeout(total=8),
            allow_redirects=True,
        ) as response:
            body = (await response.text(errors="ignore"))[:800].lower()

        if response.status == 404:
            return {"site": site, "url": url, "found": False, "status": response.status}

        for pattern in not_found_patterns:
            if pattern.lower() in body:
                return {"site": site, "url": url, "found": False, "status": response.status}

        return {
            "site": site,
            "url": url,
            "found": response.status not in (404, 410),
            "status": response.status,
        }
    except Exception:
        return {"site": site, "url": url, "found": False, "status": 0}


async def search_username(username):
    username = username.lstrip("@").strip()
    results = {
        "type": "username",
        "query": username,
        "sites": {},
        "manual_links": {},
    }

    async with aiohttp.ClientSession(headers=HEADERS) as session:
        tasks = [
            _check_site_verified(session, site, template.format(username), patterns)
            for site, (template, patterns) in USERNAME_SITES_VERIFIED.items()
        ]
        for result in await asyncio.gather(*tasks, return_exceptions=True):
            if isinstance(result, dict):
                results["sites"][result["site"]] = result

    for site, template in USERNAME_SITES_MANUAL.items():
        results["manual_links"][site] = template.format(username)

    try:
        command = [MAIGRET_BIN, username, "--timeout", "15", "--no-color"]
        loop = asyncio.get_running_loop()
        output = await loop.run_in_executor(
            None,
            lambda: subprocess.check_output(command, timeout=40, stderr=subprocess.STDOUT),
        )
        results["maigret_raw"] = output.decode("utf-8", errors="ignore")[:1500]
    except Exception:
        results["maigret_raw"] = None

    return results


async def search_email(email):
    results = {"type": "email", "query": email, "sites": {}}
    username = email.split("@")[0]

    try:
        command = [HOLEHE_BIN, email, "--no-color"]
        loop = asyncio.get_running_loop()
        output = await loop.run_in_executor(
            None,
            lambda: subprocess.check_output(command, timeout=90, stderr=subprocess.STDOUT),
        )
        raw = output.decode("utf-8", errors="ignore")
        for line in raw.splitlines():
            line = line.strip()
            site_match = re.search(r"\b[\w.-]+\.\w{2,}\b", line)
            if not site_match:
                continue
            results["sites"][site_match.group()] = {"found": line.startswith("[+]")}
    except Exception:
        pass

    results["username_also"] = await search_username(username)
    return results


def score_results(data):
    score = 0
    hits = []
    reasoning = []
    names = []
    data_type = data.get("type")

    if data_type == "phone":
        for source, info in data.get("directories", {}).items():
            if not isinstance(info, dict) or not info.get("found"):
                continue
            persons = info.get("persons", [])
            bare_names = info.get("names", [])
            score += 25
            if persons:
                for person in persons[:2]:
                    name = person.get("name", "")
                    address = person.get("street", "") or person.get("city", "")
                    if name:
                        names.append(name)
                    label = f"{name} - {address}" if name and address else (name or address or "found")
                    hits.append(f"{source}: {label}")
            elif bare_names:
                names.extend(bare_names)
                hits.append(f"{source}: {', '.join(bare_names[:2])}")
            else:
                hits.append(f"{source}: found")
        if names:
            reasoning.append("Name found in Danish directories")

    elif data_type == "username":
        found_sites = [
            site
            for site, value in data.get("sites", {}).items()
            if isinstance(value, dict) and value.get("found")
        ]
        score += min(len(found_sites) * 12, 60)
        for site in found_sites:
            hits.append(f"{site}: {data['sites'][site].get('url', '')}")
        if len(found_sites) >= 2:
            reasoning.append(f"Username confirmed on {len(found_sites)} verifiable platform(s)")

        maigret_raw = data.get("maigret_raw") or ""
        maigret_hits = len(re.findall(r"\[\+\]|\bfound\b", maigret_raw, re.IGNORECASE))
        if maigret_hits:
            score += min(maigret_hits * 5, 25)
            reasoning.append("Additional platform hits detected")

    elif data_type == "email":
        found_sites = [
            site
            for site, value in data.get("sites", {}).items()
            if isinstance(value, dict) and value.get("found")
        ]
        score += min(len(found_sites) * 10, 50)
        for site in found_sites[:10]:
            hits.append(f"{site}: registered")
        if found_sites:
            reasoning.append(f"Email registered on {len(found_sites)} platform(s)")

        username_hits = [
            site
            for site, value in data.get("username_also", {}).get("sites", {}).items()
            if isinstance(value, dict) and value.get("found")
        ]
        if username_hits:
            score += min(len(username_hits) * 5, 20)
            reasoning.append(f"Username '{data['query'].split('@')[0]}' active on {len(username_hits)} site(s)")

    score = min(score, 100)
    confidence = "HIGH" if score >= 75 else ("MEDIUM" if score >= 40 else "LOW")
    return {
        "score": score,
        "confidence": confidence,
        "hits": hits,
        "reasoning": reasoning,
        "names": list(dict.fromkeys(names))[:3],
    }


def format_report(data, analysis):
    target = data["query"]
    search_type = data["type"].upper()
    lines = [
        "VALKYRIE OSINT REPORT",
        f"Target: {target} ({search_type})",
        "",
        f"Identity Score: {analysis['score']}/100 {analysis['confidence']}",
    ]

    if analysis["names"]:
        lines.append(f"Names found: {', '.join(analysis['names'])}")

    if analysis["hits"]:
        lines.extend(["", "Confirmed hits:"])
        for hit in analysis["hits"][:10]:
            lines.append(f"- {hit}")

    if analysis["reasoning"]:
        lines.extend(["", "Analysis:"])
        for reason in analysis["reasoning"]:
            lines.append(f"- {reason}")

    if data["type"] == "username":
        social_sites = []
        adult_sites = []
        for site, url in data.get("manual_links", {}).items():
            if site in {"Pornhub", "XVideos", "OnlyFans", "Chaturbate", "Fansly", "Stripchat", "RedTube"}:
                adult_sites.append(f"- {site}: {url}")
            else:
                social_sites.append(f"- {site}: {url}")

        if social_sites:
            lines.extend(["", "Check manually - Social platforms:"])
            lines.extend(social_sites)
        if adult_sites:
            lines.extend(["", "Check manually - Adult platforms:"])
            lines.extend(adult_sites)

    if data["type"] == "phone":
        found_dirs = {
            source: info
            for source, info in data.get("directories", {}).items()
            if isinstance(info, dict) and info.get("found")
        }
        no_data = [
            source
            for source, info in data.get("directories", {}).items()
            if isinstance(info, dict) and not info.get("found")
        ]

        if found_dirs:
            lines.extend(["", "Directory results:"])
            for source, info in found_dirs.items():
                lines.append("")
                lines.append(source)
                persons = info.get("persons", [])
                bare_names = info.get("names", [])
                if persons:
                    for person in persons:
                        if person.get("name"):
                            lines.append(f"  Name: {person['name']}")
                        if person.get("street"):
                            lines.append(f"  Address: {person['street']}")
                        elif person.get("city"):
                            postal = person.get("postal", "")
                            city = person["city"]
                            lines.append(f"  City: {postal} {city}".strip())
                        if person.get("age"):
                            lines.append(f"  Age: {person['age']}")
                        if person.get("email"):
                            lines.append(f"  Email: {person['email']}")
                elif bare_names:
                    lines.append(f"  Names: {', '.join(bare_names)}")
                else:
                    lines.append("  Listing found")
                lines.append(f"  Link: {info.get('url', '')}")

        if no_data:
            lines.extend(["", f"No data: {', '.join(no_data)}"])

        social_links = data.get("social_links", {})
        if social_links:
            lines.extend(["", "Direct contact links:"])
            for app, full_url in social_links.items():
                lines.append(f"- {app}: {full_url}")

    return "\n".join(lines)


async def run_search_full(search_type, query):
    try:
        if search_type == "phone":
            data = await search_phone(query)
        elif search_type == "username":
            data = await search_username(query)
        elif search_type == "email":
            data = await search_email(query)
        else:
            return "Unknown search type.", None

        analysis = score_results(data)
        return format_report(data, analysis), data
    except Exception as exc:
        logger.error("OSINT error (%s, %s): %s", search_type, query, exc, exc_info=True)
        return f"Search error: {exc}", None


def extract_addresses(data):
    if not data or data.get("type") != "phone":
        return []

    found = []
    for source, info in data.get("directories", {}).items():
        if not isinstance(info, dict) or not info.get("found"):
            continue
        for person in info.get("persons", []):
            street = person.get("street", "")
            if street:
                found.append(
                    {
                        "label": person.get("name") or street,
                        "address": street,
                        "source": source,
                    }
                )
    return found
