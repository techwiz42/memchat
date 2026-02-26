"""Fetch and extract readable text from any URL."""

import ipaddress
import logging
import re
import socket

import httpx
from bs4 import BeautifulSoup, Tag

logger = logging.getLogger(__name__)

MAX_DOWNLOAD_BYTES = 2_000_000  # 2MB max download
MAX_PARSE_CHARS = 500_000  # chars to feed parser
MAX_TEXT_LENGTH = 8_000  # chars to return to LLM


def _is_private_url(url: str) -> bool:
    """Check if a URL resolves to a private/internal IP address."""
    try:
        from urllib.parse import urlparse
        parsed = urlparse(url)
        hostname = parsed.hostname
        if not hostname:
            return True
        # Block common internal hostnames
        if hostname in ("localhost", "metadata.google.internal"):
            return True
        # Resolve and check IP
        for info in socket.getaddrinfo(hostname, None):
            addr = info[4][0]
            ip = ipaddress.ip_address(addr)
            if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved:
                return True
    except (socket.gaierror, ValueError):
        return True  # fail closed on DNS resolution errors
    return False


async def web_fetch(url: str) -> str:
    """Fetch a URL and return its main text content.

    Args:
        url: The URL to fetch.

    Returns:
        Extracted text content, or error description on failure.
    """
    logger.info(f"Web fetch: {url!r}")

    if not url.startswith(("http://", "https://")):
        url = "https://" + url

    if _is_private_url(url):
        logger.warning(f"Web fetch blocked private/internal URL: {url!r}")
        return f"Cannot fetch internal or private URLs."

    try:
        async with httpx.AsyncClient(
            timeout=15.0,
            follow_redirects=True,
            max_redirects=5,
        ) as client:
            resp = await client.get(
                url,
                headers={
                    "User-Agent": "Mozilla/5.0 (compatible; memchat/1.0)",
                    "Accept": "text/html,application/xhtml+xml,text/plain,*/*",
                },
            )
            resp.raise_for_status()
    except httpx.TimeoutException:
        logger.error(f"Web fetch timed out: {url!r}")
        return f"Timed out fetching {url}"
    except httpx.HTTPStatusError as e:
        logger.error(f"Web fetch HTTP {e.response.status_code}: {url!r}")
        return f"Failed to fetch {url} (HTTP {e.response.status_code})"
    except Exception as e:
        logger.error(f"Web fetch error: {e}")
        return f"Failed to fetch {url}: {e}"

    content_type = resp.headers.get("content-type", "")

    # Plain text — return directly
    if "text/plain" in content_type:
        return resp.text[:MAX_TEXT_LENGTH]

    # HTML — extract readable text
    if "html" in content_type or "xml" in content_type:
        return _extract_text(resp.text, url)

    return f"Unsupported content type: {content_type}"


def _extract_text(html: str, url: str) -> str:
    """Extract readable text from HTML."""
    soup = BeautifulSoup(html[:MAX_PARSE_CHARS], "html.parser")

    # Remove non-content elements
    for tag in soup(["script", "style", "noscript", "iframe", "svg"]):
        tag.decompose()

    # Try to find main content area (ordered by specificity)
    main = (
        soup.find("article")
        or soup.find("div", id=re.compile(r"^(mw-content-text|content|main-content|article)$", re.I))
        or soup.find("div", class_=re.compile(r"(article|post|entry|content)[-_]?(body|text|content)", re.I))
        or soup.find("main")
        or soup.body
        or soup
    )

    # Remove nav/header/footer/aside within the content area
    if isinstance(main, Tag):
        for tag in main(["nav", "footer", "header", "aside", "form"]):
            tag.decompose()

    text = main.get_text(separator="\n", strip=True)

    # Collapse excessive blank lines
    text = re.sub(r"\n{3,}", "\n\n", text)

    # Skip short junk (menus, language lists, etc) at the start — find first long paragraph
    lines = text.split("\n")
    start_idx = 0
    for i, line in enumerate(lines):
        if len(line) > 80:
            start_idx = i
            break
    text = "\n".join(lines[start_idx:])

    if len(text) > MAX_TEXT_LENGTH:
        text = text[:MAX_TEXT_LENGTH] + "\n\n[Content truncated]"

    if not text.strip():
        return f"No readable text content found at {url}"

    return f"Content from {url}:\n\n{text}"
