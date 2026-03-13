"""SQLite cache for analyzed companies — neutral facts, profile-agnostic."""

import csv
import hashlib
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path

from config import config

PROMPTS_DIR = Path(__file__).resolve().parent / "prompts"

CACHE_COLUMNS = [
    "website", "company_name", "description", "industry",
    "has_product", "is_fintech", "product_type", "fintech_niche",
    "is_icp_match", "company_type", "geography_detected", "revenue_signal",
    "icp_match", "agency_type", "team_size", "size_signal", "sales_signal",
    "clutch_presence", "target_markets", "tech_stack", "outreach_score",
    "founder_niche", "stage", "audience_signal", "hook", "insight",
    "location_count", "student_count", "age_groups", "ops_signal", "growth_signal",
    "raw_page_text", "cached_at", "prompt_version",
]


def get_prompt_version(profile: str) -> str:
    """MD5 hash of prompts/{profile}.txt, first 8 chars."""
    path = PROMPTS_DIR / f"{profile}.txt"
    if not path.exists():
        return ""
    h = hashlib.md5(path.read_bytes()).hexdigest()
    return h[:8]


def _normalize_website(website: str) -> str:
    if not website:
        return ""
    s = website.lower().strip()
    s = s.replace("https://", "").replace("http://", "").replace("www.", "")
    return s.split("/")[0].split(":")[0] or ""


def _extract_neutral(data: dict) -> dict:
    """Extract profile-agnostic fields from result."""
    def _bool(v):
        if isinstance(v, bool):
            return v
        return str(v).lower() in ("true", "1", "yes")
    out = {
        "company_name": str(data.get("company_name", "") or data.get("Company Name", "")).strip(),
        "description": str(data.get("description", "")).strip(),
        "industry": str(data.get("industry", "")).strip(),
        "has_product": _bool(data.get("has_product", False)),
        "is_fintech": _bool(data.get("is_fintech", False)),
        "product_type": str(data.get("product_type", "")).strip(),
        "fintech_niche": str(data.get("fintech_niche", "")).strip(),
        "is_icp_match": _bool(data.get("is_icp_match", False)),
        "company_type": str(data.get("company_type", "")).strip(),
        "geography_detected": str(data.get("geography_detected", "")).strip(),
        "revenue_signal": str(data.get("revenue_signal", "")).strip(),
        "icp_match": _bool(data.get("icp_match", False)),
        "agency_type": str(data.get("agency_type", "")).strip(),
        "team_size": str(data.get("team_size", "")).strip(),
        "size_signal": str(data.get("size_signal", "")).strip(),
        "sales_signal": str(data.get("sales_signal", "")).strip(),
        "clutch_presence": _bool(data.get("clutch_presence", False)),
        "target_markets": str(data.get("target_markets", "")).strip(),
        "tech_stack": str(data.get("tech_stack", "")).strip(),
        "outreach_score": str(data.get("outreach_score", "")).strip(),
        "founder_niche": str(data.get("founder_niche", "")).strip(),
        "stage": str(data.get("stage", "")).strip(),
        "audience_signal": str(data.get("audience_signal", "")).strip(),
        "hook": str(data.get("hook", "")).strip(),
        "insight": str(data.get("insight", "")).strip(),
        "location_count": str(data.get("location_count", "")).strip(),
        "student_count": str(data.get("student_count", "")).strip(),
        "age_groups": str(data.get("age_groups", "")).strip(),
        "ops_signal": str(data.get("ops_signal", "")).strip(),
        "growth_signal": str(data.get("growth_signal", "")).strip(),
    }
    return out


class CompanyCache:
    def __init__(self):
        self._path = config.CACHE_FILE
        self._lock = threading.Lock()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._path)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS company_cache (
                website TEXT PRIMARY KEY,
                company_name TEXT,
                description TEXT,
                industry TEXT,
                has_product INTEGER,
                is_fintech INTEGER,
                product_type TEXT,
                fintech_niche TEXT,
                is_icp_match INTEGER,
                company_type TEXT,
                geography_detected TEXT,
                revenue_signal TEXT,
                raw_page_text TEXT,
                cached_at TEXT,
                prompt_version TEXT
            )
        """)
        for col, ctype in [
            ("is_icp_match", "INTEGER"), ("company_type", "TEXT"),
            ("geography_detected", "TEXT"), ("revenue_signal", "TEXT"),
            ("icp_match", "INTEGER"), ("agency_type", "TEXT"),
            ("team_size", "TEXT"), ("size_signal", "TEXT"), ("sales_signal", "TEXT"),
            ("clutch_presence", "INTEGER"), ("target_markets", "TEXT"),
            ("tech_stack", "TEXT"), ("outreach_score", "TEXT"),
            ("founder_niche", "TEXT"), ("stage", "TEXT"),
            ("audience_signal", "TEXT"), ("hook", "TEXT"), ("insight", "TEXT"),
            ("location_count", "TEXT"), ("student_count", "TEXT"),
            ("age_groups", "TEXT"), ("ops_signal", "TEXT"), ("growth_signal", "TEXT"),
        ]:
            try:
                conn.execute(f"ALTER TABLE company_cache ADD COLUMN {col} {ctype}")
            except sqlite3.OperationalError:
                pass
        return conn

    def get(self, website: str, prompt_version: str) -> dict | None:
        key = _normalize_website(website)
        if not key:
            return None
        with self._lock:
            conn = self._connect()
            try:
                row = conn.execute(
                    "SELECT company_name, description, industry, has_product, is_fintech, "
                    "product_type, fintech_niche, is_icp_match, company_type, geography_detected, revenue_signal, "
                    "icp_match, agency_type, team_size, size_signal, sales_signal, "
                    "clutch_presence, target_markets, tech_stack, outreach_score, "
                    "founder_niche, stage, audience_signal, hook, insight, "
                    "location_count, student_count, age_groups, ops_signal, growth_signal, "
                    "raw_page_text, cached_at, prompt_version FROM company_cache WHERE website = ?",
                    (key,),
                ).fetchone()
                if not row:
                    return None
                if row[32] != prompt_version:
                    return None
                return {
                    "website": key,
                    "company_name": row[0] or "",
                    "description": row[1] or "",
                    "industry": row[2] or "",
                    "has_product": bool(row[3]),
                    "is_fintech": bool(row[4]),
                    "product_type": row[5] or "",
                    "fintech_niche": row[6] or "",
                    "is_icp_match": bool(row[7]) if row[7] is not None else False,
                    "company_type": row[8] or "",
                    "geography_detected": row[9] or "",
                    "revenue_signal": row[10] or "",
                    "icp_match": bool(row[11]) if row[11] is not None else False,
                    "agency_type": row[12] or "",
                    "team_size": row[13] or "",
                    "size_signal": row[14] or "",
                    "sales_signal": row[15] or "",
                    "clutch_presence": bool(row[16]) if row[16] is not None else False,
                    "target_markets": row[17] or "",
                    "tech_stack": row[18] or "",
                    "outreach_score": row[19] or "",
                    "founder_niche": row[20] or "",
                    "stage": row[21] or "",
                    "audience_signal": row[22] or "",
                    "hook": row[23] or "",
                    "insight": row[24] or "",
                    "location_count": row[25] or "",
                    "student_count": row[26] or "",
                    "age_groups": row[27] or "",
                    "ops_signal": row[28] or "",
                    "growth_signal": row[29] or "",
                    "raw_page_text": row[30] or "",
                    "cached_at": row[31] or "",
                    "prompt_version": row[32] or "",
                }
            finally:
                conn.close()

    def set(
        self,
        website: str,
        data: dict,
        raw_page_text: str = "",
        prompt_version: str = "",
    ) -> None:
        key = _normalize_website(website)
        if not key:
            return
        n = _extract_neutral(data)
        with self._lock:
            conn = self._connect()
            try:
                conn.execute(
                    """INSERT OR REPLACE INTO company_cache
                    (website, company_name, description, industry, has_product, is_fintech,
                     product_type, fintech_niche, is_icp_match, company_type, geography_detected, revenue_signal,
                     icp_match, agency_type, team_size, size_signal, sales_signal,
                     clutch_presence, target_markets, tech_stack, outreach_score,
                     founder_niche, stage, audience_signal, hook, insight,
                     location_count, student_count, age_groups, ops_signal, growth_signal,
                     raw_page_text, cached_at, prompt_version)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        key,
                        n["company_name"],
                        n["description"],
                        n["industry"],
                        1 if n["has_product"] else 0,
                        1 if n["is_fintech"] else 0,
                        n["product_type"],
                        n["fintech_niche"],
                        1 if n["is_icp_match"] else 0,
                        n["company_type"],
                        n["geography_detected"],
                        n["revenue_signal"],
                        1 if n["icp_match"] else 0,
                        n["agency_type"],
                        n["team_size"],
                        n["size_signal"],
                        n["sales_signal"],
                        1 if n["clutch_presence"] else 0,
                        n["target_markets"],
                        n["tech_stack"],
                        n["outreach_score"],
                        n["founder_niche"],
                        n["stage"],
                        n["audience_signal"],
                        n["hook"],
                        n["insight"],
                        n["location_count"],
                        n["student_count"],
                        n["age_groups"],
                        n["ops_signal"],
                        n["growth_signal"],
                        raw_page_text[:10000] if raw_page_text else "",
                        datetime.now(timezone.utc).isoformat(),
                        prompt_version,
                    ),
                )
                conn.commit()
            finally:
                conn.close()

    def clear(self) -> None:
        with self._lock:
            conn = self._connect()
            try:
                conn.execute("DELETE FROM company_cache")
                conn.commit()
            finally:
                conn.close()

    def clear_old_versions(self, current_version: str) -> int:
        with self._lock:
            conn = self._connect()
            try:
                cur = conn.execute(
                    "DELETE FROM company_cache WHERE prompt_version != ? OR prompt_version IS NULL",
                    (current_version,),
                )
                conn.commit()
                return cur.rowcount
            finally:
                conn.close()

    def export_to_csv(self, filepath: str) -> None:
        with self._lock:
            conn = self._connect()
            try:
                rows = conn.execute(
                    "SELECT website, company_name, description, industry, has_product, is_fintech, "
                    "product_type, fintech_niche, is_icp_match, company_type, geography_detected, revenue_signal, "
                    "icp_match, agency_type, team_size, size_signal, sales_signal, "
                    "clutch_presence, target_markets, tech_stack, outreach_score, "
                    "founder_niche, stage, audience_signal, hook, insight, "
                    "location_count, student_count, age_groups, ops_signal, growth_signal, "
                    "raw_page_text, cached_at, prompt_version FROM company_cache"
                ).fetchall()
                with open(filepath, "w", newline="", encoding="utf-8") as f:
                    w = csv.writer(f)
                    w.writerow(CACHE_COLUMNS)
                    w.writerows(rows)
            finally:
                conn.close()

    def import_from_csv(self, filepath: str) -> int:
        imported = 0
        with self._lock:
            conn = self._connect()
            try:
                with open(filepath, "r", encoding="utf-8") as f:
                    r = csv.DictReader(f)
                    for row in r:
                        website = (row.get("website") or "").strip()
                        if not website:
                            continue
                        key = _normalize_website(website)
                        if not key:
                            continue
                        cur = conn.execute(
                            "SELECT 1 FROM company_cache WHERE website = ?", (key,)
                        ).fetchone()
                        if cur:
                            continue
                        def _b(v): return str(v).lower() in ("1", "true", "yes")
                        conn.execute(
                            """INSERT INTO company_cache
                            (website, company_name, description, industry, has_product, is_fintech,
                             product_type, fintech_niche, is_icp_match, company_type, geography_detected, revenue_signal,
                             raw_page_text, cached_at, prompt_version)
                            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                            (
                                key,
                                (row.get("company_name") or "").strip(),
                                (row.get("description") or "").strip(),
                                (row.get("industry") or "").strip(),
                                1 if _b(row.get("has_product")) else 0,
                                1 if _b(row.get("is_fintech")) else 0,
                                (row.get("product_type") or "").strip(),
                                (row.get("fintech_niche") or "").strip(),
                                1 if _b(row.get("is_icp_match")) else 0,
                                (row.get("company_type") or "").strip(),
                                (row.get("geography_detected") or "").strip(),
                                (row.get("revenue_signal") or "").strip(),
                                (row.get("raw_page_text") or "").strip()[:10000],
                                (row.get("cached_at") or datetime.now(timezone.utc).isoformat()).strip(),
                                (row.get("prompt_version") or "").strip(),
                            ),
                        )
                        imported += 1
                conn.commit()
            finally:
                conn.close()
        return imported

    def stats(self) -> dict:
        with self._lock:
            conn = self._connect()
            try:
                total = conn.execute("SELECT COUNT(*) FROM company_cache").fetchone()[0]
                row = conn.execute(
                    "SELECT MIN(cached_at), MAX(cached_at) FROM company_cache"
                ).fetchone()
                oldest = row[0] or ""
                newest = row[1] or ""
                return {"total": total, "oldest": oldest, "newest": newest}
            finally:
                conn.close()
