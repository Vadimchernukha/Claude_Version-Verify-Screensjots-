"""
Profile-specific output columns and JSON mapping.
Each profile has its own columns; website_style only when USE_SCREENSHOTS and profile supports it.
"""

from config import config

# (result_columns, qualify_key, qualify_label) — qualify_key is the boolean column name
PROFILES = {
    "fintech": {
        "columns": ["status", "is_fintech", "confidence", "fintech_niche", "fintech_reason", "analyzed_at"],
        "columns_with_style": ["status", "is_fintech", "confidence", "fintech_niche", "fintech_reason", "website_style", "analyzed_at"],
        "qualify_key": "is_fintech",
        "qualify_label": "fintech",
        "has_style": True,
        "json_map": {"is_fintech", "fintech_niche", "fintech_reason", "website_style"},
    },
    "software_product": {
        "columns": ["status", "has_product", "confidence", "product_type", "reason", "analyzed_at"],
        "columns_with_style": ["status", "has_product", "confidence", "product_type", "reason", "analyzed_at"],  # no style
        "qualify_key": "has_product",
        "qualify_label": "has product",
        "has_style": False,
        "json_map": {"has_product", "product_type", "reason"},
    },
}


def get_result_columns() -> list[str]:
    p = PROFILES.get(config.PROFILE, PROFILES["fintech"])
    if config.USE_SCREENSHOTS and p.get("has_style"):
        return p["columns_with_style"]
    return p["columns"]


def get_profile() -> dict:
    return PROFILES.get(config.PROFILE, PROFILES["fintech"])
