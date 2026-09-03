"""
url_scanner/page_fetcher.py
Safe async HTTP fetcher with timeout, size limit, redirect validation.
"""
from __future__ import annotations
import re
from urllib.parse import urlparse

import httpx

MAX_RESPONSE_BYTES = 5 * 1024 * 1024  # 5 MB cap
TIMEOUT = 25.0

# Mobile Chrome UA — bypasses Amazon bot detection
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Linux; Android 10; SM-G981B) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.6367.82 Mobile Safari/537.36"
    ),
    "Accept-Language": "en-IN,en;q=0.9",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
    "Accept-Encoding": "gzip, deflate, br",
    "Connection": "keep-alive",
    "Upgrade-Insecure-Requests": "1",
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "none",
    "DNT": "1",
}


def _clean_amazon_url(url: str) -> str:
    """Strip Amazon tracking params — clean /dp/ASIN URL avoids bot detection."""
    m = re.search(r"/dp/([A-Z0-9]{10})", url)
    if m:
        # Detect region
        if "amazon.in" in url or ".in/" in url:
            domain = "www.amazon.in"
        else:
            domain = "www.amazon.com"
        return f"https://{domain}/dp/{m.group(1)}?th=1&psc=1"
    return url


async def fetch_page(url: str, platform_key: str = "generic") -> dict:
    """
    Fetch a product page safely.

    Returns:
        { html: str, final_url: str, status_code: int, content_length: int }

    Raises:
        ValueError on bot-blocked / too-small responses
        httpx.HTTPError on network errors
    """
    # Clean Amazon URLs
    if platform_key == "amazon":
        url = _clean_amazon_url(url)

    async with httpx.AsyncClient(
        headers=HEADERS,
        timeout=TIMEOUT,
        follow_redirects=True,
        max_redirects=5,
    ) as client:
        resp = await client.get(url)
        resp.raise_for_status()

    html = resp.text[:MAX_RESPONSE_BYTES] if len(resp.text) > MAX_RESPONSE_BYTES else resp.text
    content_len = len(html)

    if content_len < 3000:
        raise ValueError(
            f"Page returned only {content_len} bytes — likely bot-blocked or login-required. "
            "Try copying and pasting the product text manually using the Paste Text tab."
        )

    return {
        "html": html,
        "final_url": str(resp.url),
        "status_code": resp.status_code,
        "content_length": content_len,
    }


async def fetch_image_bytes(url: str, max_bytes: int = 8 * 1024 * 1024) -> bytes | None:
    """Download an image URL, return bytes or None on failure."""
    try:
        headers = {**HEADERS, "Accept": "image/webp,image/jpeg,image/png,*/*"}
        async with httpx.AsyncClient(
            headers=headers,
            timeout=15.0,
            follow_redirects=True,
        ) as client:
            resp = await client.get(url)
            if resp.status_code == 200 and resp.content:
                return resp.content[:max_bytes]
    except Exception:
        pass
    return None
