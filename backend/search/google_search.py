"""Web search via DuckDuckGo Lite (no API key required)."""

import re
import html as html_mod
import logging

import httpx

logger = logging.getLogger(__name__)

DDG_LITE_URL = "https://lite.duckduckgo.com/lite/"


async def web_search(query: str, num_results: int = 5) -> str:
    """Search the web using DuckDuckGo Lite.

    Args:
        query: The search query string.
        num_results: Number of results to return.

    Returns:
        Formatted string of search results, or error description on failure.
    """
    logger.info(f"Web search: {query!r}")

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.post(
                DDG_LITE_URL,
                data={"q": query},
                headers={"User-Agent": "Mozilla/5.0 (compatible; memchat/1.0)"},
            )
            resp.raise_for_status()
            content = resp.text
    except httpx.TimeoutException:
        logger.error(f"Web search timed out for query: {query!r}")
        return "Web search timed out. Please try again."
    except Exception as e:
        logger.error(f"Web search error: {e}")
        return f"Web search failed: {e}"

    # Parse result links and snippets from DDG Lite HTML
    links = re.findall(
        r'<a rel="nofollow" href="([^"]+)" class=.result-link.>(.+?)</a>',
        content,
    )
    snippets = re.findall(
        r'<td class="result-snippet">(.*?)</td>',
        content,
        re.DOTALL,
    )

    if not links:
        return f"No results found for: {query}"

    lines = []
    for i, (url, title) in enumerate(links[:num_results]):
        title_clean = html_mod.unescape(title).strip()
        snip = ""
        if i < len(snippets):
            snip = re.sub(r"<[^>]+>", "", snippets[i])
            snip = html_mod.unescape(snip).strip()
        lines.append(f"{i + 1}. {title_clean}\n   {snip}\n   URL: {url}")

    return "\n\n".join(lines)
