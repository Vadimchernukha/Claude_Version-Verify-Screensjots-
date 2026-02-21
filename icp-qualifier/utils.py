import asyncio
import base64
import json
import re
import logging

import anthropic
import httpx

from config import config

logger = logging.getLogger(__name__)


async def fetch_page_async(website: str, http_client: httpx.AsyncClient) -> str | None:
    if not website:
        return None
    if not website.startswith("http"):
        website = f"https://{website}"

    url = f"https://r.jina.ai/{website}"
    headers = {"Authorization": f"Bearer {config.JINA_API_KEY}"}
    last_err = None
    for attempt in range(config.JINA_RETRIES):
        try:
            resp = await http_client.get(url, headers=headers, timeout=config.JINA_TIMEOUT)
            if resp.status_code >= 400:
                last_err = f"status {resp.status_code}"
                logger.warning("Jina %s: %s", website, last_err)
                return None
            text = resp.text
            if len(text) < config.JINA_MIN_LENGTH:
                last_err = f"text too short ({len(text)} chars)"
                logger.warning("Jina %s: %s", website, last_err)
                return None
            out = text[: config.PAGE_TEXT_LIMIT]
            logger.debug("Jina %s: ok, %d chars", website, len(out))
            return out
        except (httpx.TimeoutException, httpx.RequestError) as e:
            last_err = str(e)
            if attempt == config.JINA_RETRIES - 1:
                logger.warning("Jina %s: %s (after %d retries)", website, last_err, config.JINA_RETRIES)
                return None
            await asyncio.sleep(2)
    return None


async def fetch_page_playwright_async(page, url: str, timeout: int = 20000) -> str | None:
    """Fallback: get page text via Playwright when Jina fails (bypasses bot blocks)."""
    try:
        await page.goto(url, wait_until="domcontentloaded", timeout=timeout)
        await page.wait_for_timeout(1500)
        text = await page.inner_text("body")
        if not text or len(text.strip()) < config.JINA_MIN_LENGTH:
            return None
        return text[: config.PAGE_TEXT_LIMIT]
    except Exception as e:
        logger.warning("Playwright fallback %s: %s", url, e)
        return None


async def take_screenshot_async(page, url: str, timeout: int = 15000) -> str | None:
    try:
        await page.goto(url, wait_until="domcontentloaded", timeout=timeout)
        await page.wait_for_timeout(2000)
        buf = await page.screenshot(type="jpeg", quality=65, full_page=False)
        out = base64.b64encode(buf).decode("ascii")
        del buf
        return out
    except Exception as e:
        logger.warning(f"Screenshot failed for {url}: {e}")
        return None


async def call_claude_async(
    client: anthropic.AsyncAnthropic,
    prompt: str,
    screenshot_b64: str | None = None,
) -> dict | None:
    content = []
    if screenshot_b64:
        content.append({
            "type": "image",
            "source": {
                "type": "base64",
                "media_type": "image/jpeg",
                "data": screenshot_b64,
            },
        })
    content.append({"type": "text", "text": prompt})

    for attempt in range(config.MAX_RETRIES):
        try:
            response = await client.messages.create(
                model=config.MODEL,
                max_tokens=1024,
                messages=[{"role": "user", "content": content}],
            )
            out = parse_json_response(response)
            if out is None:
                logger.warning("Claude returned invalid JSON (parse failed)")
            return out
        except anthropic.RateLimitError:
            if attempt < config.MAX_RETRIES - 1:
                logger.warning(f"Rate limit hit, waiting {config.RETRY_WAIT}s...")
                await asyncio.sleep(config.RETRY_WAIT)
        except anthropic.APIError as e:
            logger.warning(f"API error on attempt {attempt + 1}: {e}")
            if attempt == config.MAX_RETRIES - 1:
                return None
            await asyncio.sleep(2)
        except Exception as e:
            logger.warning(f"Unexpected error on attempt {attempt + 1}: {e}")
            if attempt == config.MAX_RETRIES - 1:
                return None
    return None


def parse_json_response(response) -> dict | None:
    try:
        text = response.content[0].text.strip()
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
        return json.loads(text)
    except (json.JSONDecodeError, IndexError, AttributeError) as e:
        logger.debug("JSON parse error: %s", e)
        return None


def detect_stack(page_text: str, website: str) -> str:
    text_lower = page_text.lower()
    site_lower = website.lower()

    if "wp-content" in text_lower or "wordpress" in text_lower:
        return "WordPress"
    if "webflow" in text_lower or ".webflow.io" in site_lower:
        return "Webflow"
    if "framer.com" in text_lower or "framerusercontent" in text_lower:
        return "Framer"
    if "ghost.io" in text_lower:
        return "Ghost"
    if "squarespace" in text_lower:
        return "Squarespace"
    if "wix.com" in text_lower or "wixsite" in text_lower:
        return "Wix"
    if "hubspot" in text_lower and "cms" in text_lower:
        return "HubSpot CMS"
    if "shopify" in text_lower:
        return "Shopify"
    return "custom / unknown"


def safe_str(value) -> str:
    if value is None:
        return ""
    return str(value).strip()
