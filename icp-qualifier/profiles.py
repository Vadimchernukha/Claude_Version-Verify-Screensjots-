"""
Profile-specific output columns and JSON mapping.
Each profile has its own columns; website_style only when USE_SCREENSHOTS and profile supports it.
"""

from config import config

# (result_columns, qualify_key, qualify_label) — qualify_key is the boolean column name
PROFILES = {
    "fintech": {
        "profile_name": "fintech",
        "columns": ["status", "is_fintech", "confidence", "fintech_niche", "fintech_reason", "analyzed_at"],
        "columns_with_style": ["status", "is_fintech", "confidence", "fintech_niche", "fintech_reason", "website_style", "analyzed_at"],
        "qualify_key": "is_fintech",
        "qualify_label": "fintech",
        "has_style": True,
        "json_map": {"is_fintech", "fintech_niche", "fintech_reason", "website_style"},
    },
    "software_product": {
        "profile_name": "software_product",
        "columns": ["status", "has_product", "confidence", "product_type", "reason", "analyzed_at"],
        "columns_with_style": ["status", "has_product", "confidence", "product_type", "reason", "analyzed_at"],
        "qualify_key": "has_product",
        "qualify_label": "has product",
        "has_style": False,
        "json_map": {"has_product", "product_type", "reason"},
    },
    "lionwood": {
        "profile_name": "lionwood",
        "columns": ["status", "is_icp_match", "confidence", "company_type", "geography_detected", "revenue_signal", "reason", "analyzed_at"],
        "columns_with_style": ["status", "is_icp_match", "confidence", "company_type", "geography_detected", "revenue_signal", "reason", "analyzed_at"],
        "qualify_key": "is_icp_match",
        "qualify_label": "ICP match",
        "has_style": False,
        "json_map": {"is_icp_match", "company_type", "geography_detected", "revenue_signal", "reason"},
    },
    "enterprise": {
        "profile_name": "enterprise",
        "columns": ["status", "is_enterprise_match", "confidence", "company_type", "rejection_reason", "reason", "analyzed_at"],
        "columns_with_style": ["status", "is_enterprise_match", "confidence", "company_type", "rejection_reason", "reason", "analyzed_at"],
        "qualify_key": "is_enterprise_match",
        "qualify_label": "enterprise match",
        "has_style": False,
        "json_map": {"is_enterprise_match", "company_type", "rejection_reason", "reason"},
    },
    "ua_it_agency": {
        "profile_name": "ua_it_agency",
        "columns": ["status", "icp_match", "confidence", "agency_type", "team_size", "size_signal", "sales_signal", "clutch_presence", "target_markets", "tech_stack", "outreach_score", "rejection_reason", "reason", "analyzed_at"],
        "columns_with_style": ["status", "icp_match", "confidence", "agency_type", "team_size", "size_signal", "sales_signal", "clutch_presence", "target_markets", "tech_stack", "outreach_score", "rejection_reason", "reason", "analyzed_at"],
        "qualify_key": "icp_match",
        "qualify_label": "UA IT agency match",
        "has_style": False,
        "json_map": {"icp_match", "agency_type", "team_size", "size_signal", "sales_signal", "clutch_presence", "target_markets", "tech_stack", "outreach_score", "rejection_reason", "reason"},
    },
    "dance_studios": {
        "profile_name": "dance_studios",
        "columns": ["status", "icp_match", "confidence", "location_count", "student_count", "age_groups", "ops_signal", "growth_signal", "hook", "rejection_reason", "reason", "analyzed_at"],
        "columns_with_style": ["status", "icp_match", "confidence", "location_count", "student_count", "age_groups", "ops_signal", "growth_signal", "hook", "rejection_reason", "reason", "analyzed_at"],
        "qualify_key": "icp_match",
        "qualify_label": "dance studio match",
        "has_style": False,
        "json_map": {"icp_match", "location_count", "student_count", "age_groups", "ops_signal", "growth_signal", "hook", "rejection_reason", "reason"},
    },
    "echocode": {
        "profile_name": "echocode",
        "columns": ["status", "icp_match", "confidence", "founder_niche", "stage", "audience_signal", "hook", "insight", "rejection_reason", "reason", "analyzed_at"],
        "columns_with_style": ["status", "icp_match", "confidence", "founder_niche", "stage", "audience_signal", "hook", "insight", "website_style", "rejection_reason", "reason", "analyzed_at"],
        "qualify_key": "icp_match",
        "qualify_label": "Echocode ICP match",
        "has_style": True,
        "json_map": {"icp_match", "founder_niche", "stage", "audience_signal", "hook", "insight", "website_style", "rejection_reason", "reason"},
    },
}


def get_result_columns() -> list[str]:
    p = PROFILES.get(config.PROFILE, PROFILES["fintech"])
    if config.USE_SCREENSHOTS and p.get("has_style"):
        return p["columns_with_style"]
    return p["columns"]


def get_profile() -> dict:
    return PROFILES.get(config.PROFILE, PROFILES["fintech"])
