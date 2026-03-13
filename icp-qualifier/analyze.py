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
    preprocess_page_text, safe_str,
)
from cache import CompanyCache, get_prompt_version

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
    elif profile["qualify_key"] == "is_enterprise_match":
        def _s(v):
            if v is None:
                return ""
            v = str(v).strip()
            return "" if v.lower() in ("none", "null") else v
        res["is_enterprise_match"] = result.get("is_enterprise_match", False)
        res["confidence"] = result.get("confidence", "low")
        res["company_type"] = _s(result.get("company_type"))
        res["rejection_reason"] = _s(result.get("rejection_reason"))
        res["reason"] = _s(result.get("reason"))
    elif profile["qualify_key"] == "is_icp_match":
        def _clean(s):
            if s is None:
                return ""
            s = str(s).strip()
            if s.lower() in ("none", "null"):
                return ""
            for prefix in ("None — ", "none — "):
                if s.startswith(prefix):
                    s = s[len(prefix):].strip()
            return s
        res["is_icp_match"] = result.get("is_icp_match", False)
        res["confidence"] = result.get("confidence", "low")
        res["company_type"] = _clean(result.get("company_type"))
        res["geography_detected"] = _clean(result.get("geography_detected"))
        res["revenue_signal"] = _clean(result.get("revenue_signal"))
        res["reason"] = _clean(result.get("reason"))
    elif profile["qualify_key"] == "icp_match":
        def _s(v):
            if v is None:
                return ""
            v = str(v).strip()
            return "" if v.lower() in ("none", "null") else v
        res["icp_match"] = result.get("icp_match", False)
        res["confidence"] = result.get("confidence", "low")
        res["rejection_reason"] = _s(result.get("rejection_reason"))
        res["reason"] = _s(result.get("reason"))
        if profile.get("profile_name") == "dance_studios":
            res["location_count"] = _s(result.get("location_count"))
            res["student_count"] = _s(result.get("student_count"))
            res["age_groups"] = _s(result.get("age_groups"))
            res["ops_signal"] = _s(result.get("ops_signal"))
            res["growth_signal"] = _s(result.get("growth_signal"))
            res["hook"] = _s(result.get("hook"))
        elif profile.get("profile_name") == "echocode":
            res["founder_niche"] = _s(result.get("founder_niche"))
            res["stage"] = _s(result.get("stage"))
            res["audience_signal"] = _s(result.get("audience_signal"))
            res["hook"] = _s(result.get("hook"))
            res["insight"] = _s(result.get("insight"))
            if "website_style" in cols:
                raw = result.get("website_style", "")
                res["website_style"] = raw if raw in VALID_STYLES else "Mixed"
        else:
            res["agency_type"] = _s(result.get("agency_type"))
            res["team_size"] = _s(result.get("team_size"))
            res["size_signal"] = _s(result.get("size_signal"))
            res["sales_signal"] = _s(result.get("sales_signal"))
            res["clutch_presence"] = result.get("clutch_presence", False)
            res["target_markets"] = _s(result.get("target_markets"))
            res["tech_stack"] = _s(result.get("tech_stack"))
            res["outreach_score"] = _s(result.get("outreach_score"))
    else:
        res["has_product"] = result.get("has_product", False)
        res["confidence"] = result.get("confidence", "low")
        res["product_type"] = result.get("product_type") or ""
        res["reason"] = result.get("reason", "")

    real_name = result.get("company_name", "").strip()
    if real_name:
        res["Company Name"] = real_name
    return res


def _cache_to_result(cached: dict, profile: dict) -> dict:
    """Map cached neutral fields to profile-specific output format."""
    base = {
        "company_name": cached.get("company_name", ""),
        "confidence": "medium",
        "fintech_reason": "",
        "reason": "",
    }
    if profile["qualify_key"] == "is_fintech":
        base["is_fintech"] = cached.get("is_fintech", False)
        base["fintech_niche"] = cached.get("fintech_niche", "")
        base["website_style"] = "Mixed"
    elif profile["qualify_key"] == "is_enterprise_match":
        base["is_enterprise_match"] = cached.get("is_enterprise_match", False)
        base["company_type"] = cached.get("company_type", "")
        base["rejection_reason"] = cached.get("rejection_reason", "")
    elif profile["qualify_key"] == "is_icp_match":
        base["is_icp_match"] = cached.get("is_icp_match", False)
        base["company_type"] = cached.get("company_type", "")
        base["geography_detected"] = cached.get("geography_detected", "")
        base["revenue_signal"] = cached.get("revenue_signal", "")
    elif profile["qualify_key"] == "icp_match":
        base["icp_match"] = cached.get("icp_match", False)
        base["rejection_reason"] = cached.get("rejection_reason", "")
        if profile.get("profile_name") == "dance_studios":
            base["location_count"] = cached.get("location_count", "")
            base["student_count"] = cached.get("student_count", "")
            base["age_groups"] = cached.get("age_groups", "")
            base["ops_signal"] = cached.get("ops_signal", "")
            base["growth_signal"] = cached.get("growth_signal", "")
            base["hook"] = cached.get("hook", "")
        elif profile.get("profile_name") == "echocode":
            base["founder_niche"] = cached.get("founder_niche", "")
            base["stage"] = cached.get("stage", "")
            base["audience_signal"] = cached.get("audience_signal", "")
            base["hook"] = cached.get("hook", "")
            base["insight"] = cached.get("insight", "")
            base["website_style"] = "Mixed"
        else:
            base["agency_type"] = cached.get("agency_type", "")
            base["team_size"] = cached.get("team_size", "")
            base["size_signal"] = cached.get("size_signal", "")
            base["sales_signal"] = cached.get("sales_signal", "")
            base["clutch_presence"] = cached.get("clutch_presence", False)
            base["target_markets"] = cached.get("target_markets", "")
            base["tech_stack"] = cached.get("tech_stack", "")
            base["outreach_score"] = cached.get("outreach_score", "")
    else:
        base["has_product"] = cached.get("has_product", False)
        base["product_type"] = cached.get("product_type", "")
    return _map_result_to_columns(base, profile)


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
    if config.USE_CACHE:
        prompt_version = get_prompt_version(config.PROFILE)
        cached = CompanyCache().get(website, prompt_version)
        if cached is not None:
            return _cache_to_result(cached, profile)

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

        if page_text is not None:
            page_text = preprocess_page_text(page_text, max_chars=config.PROCESSED_TEXT_LIMIT)

        prompt = prompt_template.format(
            company_name=company_name,
            page_text=page_text or "(text not available — use the screenshot only)",
        )

        result = await call_claude_async(claude_client, prompt, screenshot_b64=screenshot_b64)
        del screenshot_b64

        if result is not None and result.get("confidence") == "low":
            retry_result = await call_claude_async(
                claude_client, prompt, model=config.FALLBACK_MODEL
            )
            if retry_result is not None:
                result = retry_result

        if result is None:
            return {
                "status": "error",
                "analyzed_at": datetime.now(timezone.utc).isoformat(),
            }

        mapped = _map_result_to_columns(result, profile)
        if config.USE_CACHE:
            CompanyCache().set(
                website,
                {**result, "Company Name": result.get("company_name", "")},
                raw_page_text=page_text or "",
                prompt_version=get_prompt_version(config.PROFILE),
            )
        return mapped


async def _run_async(
    df: pd.DataFrame,
    existing: pd.DataFrame | None,
    progress_callback: Callable[[int, int, str], None] | None = None,
) -> pd.DataFrame:
    prompt_template = load_prompt()
    profile = get_profile()
    result_cols = get_result_columns()
    qualify_key = profile["qualify_key"]
    qualify_label = profile["qualify_label"]
    claude_client = anthropic.AsyncAnthropic(api_key=config.ANTHROPIC_API_KEY)

    already_done: set[str] = set()
    if existing is not None and "status" in existing.columns and "Website" in existing.columns:
        status_ok = existing["status"].notna() & (existing["status"] != "")
        unreachable_or_error = status_ok & existing["status"].isin(["unreachable"])
        if qualify_key in existing.columns:
            analyzed_with_result = (
                status_ok & (existing["status"] == "analyzed")
                & existing[qualify_key].notna()
                & (existing[qualify_key].astype(str).str.strip() != "")
            )
            done_mask = unreachable_or_error | analyzed_with_result
        else:
            done_mask = unreachable_or_error
        already_done = set(existing.loc[done_mask, "Website"].astype(str).str.strip().str.lower())
        logger.info("Resume: %d companies already done (by Website)", len(already_done))

    for col in result_cols:
        if col not in df.columns:
            df[col] = ""

    has_website = df[df["Website"].str.strip() != ""]
    stats = {"qualified": 0, "not_qualified": 0, "Legacy": 0, "Mixed": 0, "Modern": 0, "unreachable": 0, "error": 0}

    tasks_info = []
    for idx, row in has_website.iterrows():
        company_name = safe_str(row.get("Company Name"))
        website = safe_str(row.get("Website"))
        website_key = website.lower().strip() if website else ""
        if website_key in already_done:
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
                    elif qualify_key in ("is_icp_match", "is_enterprise_match"):
                        niche = res.get("company_type", "")
                    elif qualify_key == "icp_match":
                        niche = res.get("agency_type", "") or res.get("founder_niche", "")
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
