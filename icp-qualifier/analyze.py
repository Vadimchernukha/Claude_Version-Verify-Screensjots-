import asyncio
import gc
import logging
from collections.abc import Callable
from datetime import datetime, timezone

import pandas as pd
import anthropic
import httpx
from tqdm import tqdm

from config import config
from profiles import get_result_columns, get_profile
from prompts import load_prompt
from utils import (
    fetch_page_async, fetch_page_playwright_async, take_screenshot_async, call_claude_async,
    safe_str,
)

logger = logging.getLogger(__name__)

STYLE_ICONS = {"Legacy": "🔴", "Mixed": "🟡", "Modern": "🟢"}
VALID_STYLES = {"Legacy", "Mixed", "Modern"}


def _normalize_url(website: str) -> str:
    if not website:
        return ""
    if not website.startswith("http"):
        return f"https://{website}"
    return website


def _map_result_to_columns(result: dict, profile: dict) -> dict:
    """Map Claude JSON response to profile-specific output columns."""
    cols = get_result_columns()
    res = {"status": "analyzed", "analyzed_at": datetime.now(timezone.utc).isoformat()}

    if profile["qualify_key"] == "is_fintech":
        res["is_fintech"] = result.get("is_fintech", False)
        res["confidence"] = result.get("confidence", "low")
        res["fintech_niche"] = result.get("fintech_niche") or ""
        res["fintech_reason"] = result.get("fintech_reason", "")
        if "website_style" in cols:
            raw = result.get("website_style", "")
            res["website_style"] = raw if raw in VALID_STYLES else "Mixed"
    else:
        res["has_product"] = result.get("has_product", False)
        res["confidence"] = result.get("confidence", "low")
        res["product_type"] = result.get("product_type") or ""
        res["reason"] = result.get("reason", "")

    real_name = result.get("company_name", "").strip()
    if real_name:
        res["Company Name"] = real_name
    return res


async def _process_one(
    company_name: str,
    website: str,
    prompt_template: str,
    profile: dict,
    claude_client: anthropic.AsyncAnthropic,
    http_client: httpx.AsyncClient,
    browser,
    semaphore: asyncio.Semaphore,
) -> dict:
    async with semaphore:
        full_url = _normalize_url(website)

        screenshot_b64 = None
        if config.USE_SCREENSHOTS and browser and full_url:
            page = await browser.new_page(viewport={"width": 1440, "height": 900})
            try:
                jina_task = fetch_page_async(website, http_client)
                screenshot_task = take_screenshot_async(page, full_url)
                page_text, screenshot_b64 = await asyncio.gather(jina_task, screenshot_task)
            finally:
                await page.close()
        else:
            page_text = await fetch_page_async(website, http_client)
            if page_text is None and browser and config.JINA_FALLBACK_PLAYWRIGHT and full_url:
                page = await browser.new_page(viewport={"width": 1440, "height": 900})
                try:
                    page_text = await fetch_page_playwright_async(page, full_url)
                    if page_text:
                        logger.info("Playwright fallback ok: %s", website)
                finally:
                    await page.close()

        if page_text is None and screenshot_b64 is None:
            return {"status": "unreachable", "analyzed_at": datetime.now(timezone.utc).isoformat()}

        prompt = prompt_template.format(
            company_name=company_name,
            page_text=page_text or "(text not available — use the screenshot only)",
        )

        result = await call_claude_async(claude_client, prompt, screenshot_b64=screenshot_b64)
        del screenshot_b64

        if result is None:
            return {
                "status": "error",
                "analyzed_at": datetime.now(timezone.utc).isoformat(),
            }

        return _map_result_to_columns(result, profile)


async def _run_async(
    df: pd.DataFrame,
    existing: pd.DataFrame | None,
    progress_callback: Callable[[int, int, str], None] | None = None,
) -> pd.DataFrame:
    prompt_template = load_prompt()
    profile = get_profile()
    result_cols = get_result_columns()
    claude_client = anthropic.AsyncAnthropic(api_key=config.ANTHROPIC_API_KEY)

    already_done: set[str] = set()
    if existing is not None and "status" in existing.columns and "Website" in existing.columns:
        done_mask = existing["status"].notna() & (existing["status"] != "")
        already_done = set(existing.loc[done_mask, "Website"].astype(str).str.strip().str.lower())
        logger.info("Resume: %d companies already done (by Website)", len(already_done))

    for col in result_cols:
        if col not in df.columns:
            df[col] = ""

    has_website = df[df["Website"].str.strip() != ""]
    qualify_key = profile["qualify_key"]
    qualify_label = profile["qualify_label"]
    stats = {"qualified": 0, "not_qualified": 0, "Legacy": 0, "Mixed": 0, "Modern": 0, "unreachable": 0, "error": 0}

    tasks_info = []
    for idx, row in has_website.iterrows():
        company_name = safe_str(row.get("Company Name"))
        website = safe_str(row.get("Website"))
        website_key = website.lower().strip() if website else ""
        if website_key in already_done or safe_str(df.at[idx, "status"]):
            continue
        tasks_info.append((idx, company_name, website))

    skipped = len(has_website) - len(tasks_info)
    if skipped:
        logger.info("Skipping %d already processed companies", skipped)
        print(f"Skipping {skipped} already processed companies")

    mode = "text + screenshot" if config.USE_SCREENSHOTS else "text only"
    logger.info("Analyzing %d companies (workers=%d, mode=%s)", len(tasks_info), config.WORKERS, mode)
    print(f"\n=== Analyzing {len(tasks_info)} companies ({config.WORKERS} workers, {mode}) ===")
    print(f"Profile: {config.PROFILE}")

    if not tasks_info:
        print("Nothing to process.")
        return df

    total = len(tasks_info)
    if progress_callback:
        progress_callback(0, total, "Initializing...")

    semaphore = asyncio.Semaphore(config.WORKERS)

    browser = None
    pw_instance = None

    if config.USE_SCREENSHOTS or (config.JINA_FALLBACK_PLAYWRIGHT and not config.USE_SCREENSHOTS):
        if progress_callback:
            progress_callback(0, total, "Launching browser...")
        logger.info("Launching Playwright Chromium (headless)")
        from playwright.async_api import async_playwright
        pw_instance = await async_playwright().start()
        browser = await pw_instance.chromium.launch(
            headless=True,
            args=[
                "--disable-dev-shm-usage",
                "--disable-gpu",
                "--no-sandbox",
                "--disable-software-rasterizer",
                "--disable-extensions",
                "--disable-background-networking",
                "--disable-default-apps",
                "--disable-sync",
            ],
        )

    try:
        if progress_callback:
            progress_callback(0, total, "Starting analysis...")
        async with httpx.AsyncClient(
            limits=httpx.Limits(max_connections=config.WORKERS + 2, max_keepalive_connections=2),
        ) as http_client:
            pbar = tqdm(total=len(tasks_info), unit="co", leave=False)

            async def _wrapped(idx, company_name, website):
                logger.debug("Processing: %s (%s)", company_name, website)
                res = await _process_one(
                    company_name, website, prompt_template, profile,
                    claude_client, http_client, browser, semaphore,
                )
                for k, v in res.items():
                    df.at[idx, k] = str(v) if v is not None else ""

                status = res.get("status", "")
                if status == "unreachable":
                    tqdm.write(f"{company_name:<30} → unreachable ⚠️")
                    stats["unreachable"] += 1
                elif status == "error":
                    tqdm.write(f"{company_name:<30} → Claude error ⚠️")
                    stats["error"] += 1
                else:
                    is_ok = res.get(qualify_key, False)
                    conf = res.get("confidence", "")
                    if qualify_key == "is_fintech":
                        niche = res.get("fintech_niche", "")
                    else:
                        niche = res.get("product_type", "")
                    ft_icon = "✅" if is_ok else "❌"
                    c_icon = {"high": "🟢", "medium": "🟡", "low": "🔴"}.get(conf, "❓")
                    line = f"{company_name:<30} {ft_icon}{c_icon} {niche:<36}"
                    if "website_style" in res and profile.get("has_style"):
                        style = res.get("website_style", "")
                        s_icon = STYLE_ICONS.get(style, "❓")
                        line += f" {s_icon} {style}"
                        stats[style] = stats.get(style, 0) + 1
                    tqdm.write(line)
                    if is_ok:
                        stats["qualified"] += 1
                    else:
                        stats["not_qualified"] += 1

                df.to_csv(config.OUTPUT_FILE, index=False)
                logger.debug("Saved progress: %s -> %s", company_name, res.get("status", ""))
                pbar.update(1)
                if progress_callback:
                    progress_callback(pbar.n, total, f"{company_name} — {res.get('status', 'ok')}")
                if pbar.n % 15 == 0 and pbar.n > 0:
                    gc.collect()

            tasks = [_wrapped(idx, cn, ws) for idx, cn, ws in tasks_info]
            await asyncio.gather(*tasks)
            pbar.close()

    finally:
        if browser:
            await browser.close()
        if pw_instance:
            await pw_instance.stop()
        gc.collect()

    logger.info(
        "Done: %s=%d | not=%d | unreachable=%d | error=%d",
        qualify_label, stats["qualified"], stats["not_qualified"], stats["unreachable"], stats["error"],
    )
    print(
        f"\nDone: {qualify_label}={stats['qualified']} | not={stats['not_qualified']} | "
        f"unreachable={stats['unreachable']}"
    )
    if profile.get("has_style") and config.USE_SCREENSHOTS:
        print(
            f"Styles: Legacy={stats['Legacy']} | Mixed={stats['Mixed']} | Modern={stats['Modern']}"
        )
    return df


def run_analysis(
    df: pd.DataFrame,
    existing: pd.DataFrame | None,
    progress_callback: Callable[[int, int, str], None] | None = None,
) -> pd.DataFrame:
    return asyncio.run(_run_async(df, existing, progress_callback))
