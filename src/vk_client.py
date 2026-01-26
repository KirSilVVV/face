import re
import logging
from typing import Optional
import httpx

from src.config import VK_ACCESS_TOKEN

logger = logging.getLogger(__name__)

VK_API_URL = "https://api.vk.com/method"
VK_API_VERSION = "5.131"


def extract_vk_username(url: str) -> Optional[str]:
    """Extract username or ID from VK URL."""
    # Patterns:
    # vk.com/username
    # vk.com/id123456
    # m.vk.com/username
    patterns = [
        r'(?:https?://)?(?:m\.)?vk\.com/([a-zA-Z0-9_.]+)',
    ]

    for pattern in patterns:
        match = re.search(pattern, url)
        if match:
            username = match.group(1)
            # Skip service pages
            if username in ('wall', 'photo', 'video', 'audio', 'feed', 'im', 'friends'):
                return None
            return username
    return None


async def get_vk_user_info(user_id: str) -> Optional[dict]:
    """Get user info from VK API."""
    if not VK_ACCESS_TOKEN:
        logger.warning("VK_ACCESS_TOKEN not set, skipping VK lookup")
        return None

    params = {
        "user_ids": user_id,
        "fields": "first_name,last_name,screen_name",
        "access_token": VK_ACCESS_TOKEN,
        "v": VK_API_VERSION
    }

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(f"{VK_API_URL}/users.get", params=params)

            if response.status_code != 200:
                logger.error(f"VK API error: {response.status_code}")
                return None

            data = response.json()

            if "error" in data:
                logger.error(f"VK API error: {data['error']}")
                return None

            users = data.get("response", [])
            if users:
                return users[0]
            return None

    except Exception as e:
        logger.error(f"VK API request failed: {e}")
        return None


async def get_name_from_vk_url(url: str) -> Optional[str]:
    """Extract name from VK profile URL."""
    username = extract_vk_username(url)
    if not username:
        return None

    user_info = await get_vk_user_info(username)
    if not user_info:
        return None

    first_name = user_info.get("first_name", "")
    last_name = user_info.get("last_name", "")

    if first_name and last_name:
        return f"{first_name} {last_name}"
    elif first_name:
        return first_name
    return None


async def extract_names_from_urls(urls: list[str]) -> dict[str, str]:
    """Extract names from list of URLs. Returns {url: name}."""
    names = {}

    for url in urls:
        if "vk.com" in url.lower():
            name = await get_name_from_vk_url(url)
            if name:
                names[url] = name

    return names


def guess_name_from_username(username: str) -> Optional[str]:
    """Try to guess name from username patterns like ivan_petrov, ivan.petrov."""
    # Remove common prefixes/suffixes
    clean = username.lower()
    for prefix in ['id', 'club', 'public']:
        if clean.startswith(prefix) and clean[len(prefix):].isdigit():
            return None

    # Split by common separators
    parts = re.split(r'[._\-]', username)

    if len(parts) >= 2:
        # Capitalize each part
        name_parts = [p.capitalize() for p in parts if p and len(p) > 1]
        if len(name_parts) >= 2:
            return " ".join(name_parts[:2])

    return None
