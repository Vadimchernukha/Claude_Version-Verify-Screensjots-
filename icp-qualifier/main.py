#!/usr/bin/env python3
"""
ICP Qualifier — Profile-based company qualification (fintech, software_product, etc.)
Usage: python main.py
"""

import logging
import os
import sys

import pandas as pd

from config import config
from profiles import get_result_columns

log_level = getattr(logging, config.LOG_LEVEL.upper(), logging.INFO)
logging.basicConfig(
    level=logging.WARNING,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(config.LOG_FILE, encoding="utf-8"),
    ],
)
for name in ("__main__", "analyze", "utils", "prompts"):
    logging.getLogger(name).setLevel(log_level)
for name in ("httpcore", "httpx", "anthropic", "asyncio"):
    logging.getLogger(name).setLevel(logging.WARNING)
logger = logging.getLogger(__name__)


def _validate_env() -> None:
    missing = []
    if not config.ANTHROPIC_API_KEY:
        missing.append("ANTHROPIC_API_KEY")
    if not config.JINA_API_KEY:
        missing.append("JINA_API_KEY")
    if missing:
        print(f"ERROR: Missing env vars: {', '.join(missing)}")
        print("Copy .env.example → .env and fill in your API keys.")
        sys.exit(1)


def _detect_delimiter(filepath: str) -> str:
    with open(filepath, "r", encoding="utf-8") as f:
        first_line = f.readline()
    if "\t" in first_line:
        return "\t"
    return ","


def _looks_like_url(val: str) -> bool:
    v = val.strip().lower()
    if v.startswith("http") or v.startswith("www."):
        return True
    if "." in v and "/" in v:
        return True
    parts = v.split(".")
    if len(parts) >= 2 and len(parts[-1]) >= 2 and " " not in v:
        return True
    return False


def _looks_like_linkedin(val: str) -> bool:
    return "linkedin.com" in val.lower()


def _normalize_columns(df: pd.DataFrame) -> pd.DataFrame:
    standard_cols = {"Company Name", "Website", "Company Description", "Short Description", "Industry", "Keywords"}
    if standard_cols & set(df.columns):
        for c in ["Company Name", "Website"]:
            if c not in df.columns:
                df[c] = ""
        return df

    cols = list(df.columns)
    url_cols = [c for c in cols if df[c].apply(_looks_like_url).mean() > 0.5]
    linkedin_cols = [c for c in url_cols if df[c].apply(_looks_like_linkedin).mean() > 0.3]
    site_cols = [c for c in url_cols if c not in linkedin_cols]

    rename = {}
    if site_cols:
        rename[site_cols[0]] = "Website"
    elif url_cols:
        rename[url_cols[0]] = "Website"

    if linkedin_cols:
        rename[linkedin_cols[0]] = "LinkedIn"

    non_url = [c for c in cols if c not in url_cols]
    if non_url:
        rename[non_url[0]] = "Company Name"
        remaining = [c for c in non_url[1:] if c not in rename]
        if remaining:
            rename[remaining[0]] = "Company Description"

    df = df.rename(columns=rename)

    if "Website" in df.columns and "Company Name" not in df.columns:
        df["Company Name"] = df["Website"].apply(
            lambda x: x.strip().lower().replace("https://", "").replace("http://", "").replace("www.", "").rstrip("/").split("/")[0]
        )
    for c in ["Company Name", "Website"]:
        if c not in df.columns:
            df[c] = ""
    return df


def _load_input() -> pd.DataFrame:
    if not os.path.exists(config.INPUT_FILE):
        logger.error("Input file not found: %s", config.INPUT_FILE)
        print(f"ERROR: {config.INPUT_FILE} not found.")
        sys.exit(1)

    sep = _detect_delimiter(config.INPUT_FILE)
    logger.debug("Detected delimiter: %r", sep)
    df = pd.read_csv(config.INPUT_FILE, sep=sep, dtype=str, engine="python").fillna("")

    if all(str(c).isdigit() for c in df.columns) or (
        len(df.columns) <= 5 and not {"Company Name", "Website"} & set(df.columns)
    ):
        df = pd.read_csv(config.INPUT_FILE, sep=sep, dtype=str, header=None, engine="python").fillna("")
        logger.debug("Auto-normalized columns (no header)")

    df = _normalize_columns(df)
    df = df[df["Company Name"].str.strip() != ""].reset_index(drop=True)

    logger.info("Loaded %d companies from %s", len(df), config.INPUT_FILE)
    print(f"Loaded {len(df)} companies from {config.INPUT_FILE}")
    return df


def _load_existing() -> pd.DataFrame | None:
    if not os.path.exists(config.OUTPUT_FILE) or os.path.getsize(config.OUTPUT_FILE) < 10:
        return None
    try:
        existing = pd.read_csv(config.OUTPUT_FILE, dtype=str).fillna("")
        if existing.empty or len(existing.columns) < 2:
            return None
        logger.info("Found existing output: %s (%d rows), will resume", config.OUTPUT_FILE, len(existing))
        print(f"Found existing {config.OUTPUT_FILE} ({len(existing)} rows) — resuming...")
        return existing
    except Exception as e:
        logger.warning("Could not read existing output: %s", e)
        print(f"WARNING: Could not read {config.OUTPUT_FILE}, starting fresh.")
    return None


def _merge_existing(df: pd.DataFrame, existing: pd.DataFrame) -> pd.DataFrame:
    progress_cols = get_result_columns()
    merge_col = "Website" if "Website" in existing.columns else "Company Name"
    existing_cols = [merge_col] + [c for c in progress_cols if c in existing.columns]
    existing_progress = existing[existing_cols].drop_duplicates(subset=[merge_col], keep="last")
    df = df.drop(columns=[c for c in progress_cols if c in df.columns], errors="ignore")
    df = df.merge(existing_progress, on=merge_col, how="left")
    for col in progress_cols:
        if col not in df.columns:
            df[col] = ""
    df = df.fillna("")
    merged_count = existing_progress[merge_col].nunique()
    logger.info("Merged existing progress: %d rows by %s", merged_count, merge_col)
    return df


def _print_summary(df: pd.DataFrame) -> None:
    print("\n=== FINAL SUMMARY ===")

    analyzed = df[df["status"] == "analyzed"]
    unreachable = (df["status"] == "unreachable").sum()

    profile = __import__("profiles", fromlist=["get_profile"]).get_profile()
    qualify_key = profile["qualify_key"]
    qualify_label = profile["qualify_label"]

    if qualify_key in df.columns and not analyzed.empty:
        qualified = analyzed[analyzed[qualify_key].astype(str).str.lower() == "true"]
        not_qualified = analyzed[analyzed[qualify_key].astype(str).str.lower() == "false"]
        print(f"{qualify_label}: {len(qualified)} | Not: {len(not_qualified)} | Unreachable: {unreachable}")

        if "website_style" in df.columns and profile.get("has_style") and not analyzed.empty:
            styles = analyzed["website_style"].value_counts()
            print(
                f"Styles:  Legacy={styles.get('Legacy', 0)} | "
                f"Mixed={styles.get('Mixed', 0)} | "
                f"Modern={styles.get('Modern', 0)}"
            )

    print(f"Saved to: {config.OUTPUT_FILE}")


def main() -> None:
    logger.info("=== ICP Qualifier start (profile=%s, screenshots=%s) ===", config.PROFILE, config.USE_SCREENSHOTS)
    _validate_env()

    df = _load_input()
    existing = _load_existing()

    if existing is not None:
        df = _merge_existing(df, existing)

    from analyze import run_analysis
    df = run_analysis(df, existing)
    del existing

    df.to_csv(config.OUTPUT_FILE, index=False)
    logger.info("Saved output to %s", config.OUTPUT_FILE)
    _print_summary(df)
    logger.info("=== ICP Qualifier done ===")


if __name__ == "__main__":
    main()
