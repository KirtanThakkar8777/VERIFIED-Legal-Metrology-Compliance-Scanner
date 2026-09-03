"""
url_scanner/platform_detector.py
Detect marketplace from URL + SSRF guard.
"""
from __future__ import annotations
import ipaddress
import re
from urllib.parse import urlparse


# ── Known platforms ────────────────────────────────────────────────────────────

PLATFORMS = [
    ("amazon",         "Amazon"),
    ("flipkart",       "Flipkart"),
    ("meesho",         "Meesho"),
    ("myntra",         "Myntra"),
    ("jiomart",        "JioMart"),
    ("bigbasket",      "BigBasket"),
    ("blinkit",        "Blinkit"),
    ("zepto",          "Zepto"),
    ("swiggy",         "Swiggy Instamart"),
    ("tatacliq",       "Tata Cliq"),
    ("ajio",           "AJIO"),
    ("snapdeal",       "Snapdeal"),
    ("nykaa",          "Nykaa"),
    ("firstcry",       "FirstCry"),
    ("purplle",        "Purplle"),
    ("healthkart",     "HealthKart"),
]

# JS-heavy platforms that need headless browser for real data
JS_HEAVY = {"Meesho", "Myntra", "Blinkit", "Zepto", "Swiggy Instamart", "Tata Cliq", "AJIO"}

# Private / internal IP ranges
_PRIVATE_RANGES = [
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("172.16.0.0/12"),
    ipaddress.ip_network("192.168.0.0/16"),
    ipaddress.ip_network("127.0.0.0/8"),
    ipaddress.ip_network("169.254.0.0/16"),
    ipaddress.ip_network("::1/128"),
    ipaddress.ip_network("fc00::/7"),
]


def _is_private_ip(host: str) -> bool:
    try:
        addr = ipaddress.ip_address(host)
        return any(addr in net for net in _PRIVATE_RANGES)
    except ValueError:
        return False


def validate_url(url: str) -> None:
    """
    Raise ValueError if the URL is invalid or unsafe (SSRF guard).
    Allowed: http:// and https:// with public hosts only.
    """
    url = url.strip()
    if not url:
        raise ValueError("URL cannot be empty.")

    parsed = urlparse(url)

    if parsed.scheme not in ("http", "https"):
        raise ValueError(
            f"Only http:// and https:// URLs are allowed. Got: {parsed.scheme}://"
        )

    host = parsed.hostname or ""
    if not host:
        raise ValueError("URL has no valid hostname.")

    # Block localhost variants
    if host in ("localhost", "localhost."):
        raise ValueError("Localhost URLs are not allowed.")

    # Block numeric private IPs
    if _is_private_ip(host):
        raise ValueError(f"Private/internal IP addresses are not allowed: {host}")

    # Block numeric IPs that look internal (simple check)
    if re.match(r"^\d+\.\d+\.\d+\.\d+$", host):
        raise ValueError("Direct IP address URLs are not allowed for security reasons.")


def detect_platform(url: str) -> dict:
    """
    Detect marketplace from URL.

    Returns:
        {
          platform: str,        # e.g. "Amazon"
          adapter_key: str,     # e.g. "amazon"
          is_supported: bool,
          is_js_heavy: bool,    # True if JS rendering required for full data
          display_name: str,
        }
    """
    ul = url.lower()
    for key, name in PLATFORMS:
        if key in ul:
            return {
                "platform": name,
                "adapter_key": key,
                "is_supported": True,
                "is_js_heavy": name in JS_HEAVY,
                "display_name": name,
            }
    return {
        "platform": "Generic",
        "adapter_key": "generic",
        "is_supported": True,
        "is_js_heavy": False,
        "display_name": "Generic E-Commerce Website",
    }
