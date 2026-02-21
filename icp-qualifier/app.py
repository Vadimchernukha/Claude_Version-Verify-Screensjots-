#!/usr/bin/env python3
"""ICP Qualifier — minimal Streamlit UI
Run: streamlit run app.py
"""

import io
import sys
from pathlib import Path

import pandas as pd
import streamlit as st

# Ensure project root is in path
sys.path.insert(0, str(Path(__file__).resolve().parent))

from config import config
from profiles import get_profile, get_result_columns

st.set_page_config(page_title="ICP Qualifier", page_icon="🔍", layout="centered")

st.title("ICP Qualifier")
st.caption("Qualify companies by profile (fintech, software product)")

# Sidebar
with st.sidebar:
    profile = st.selectbox(
        "Profile",
        options=["software_product", "fintech"],
        format_func=lambda x: "Software Product" if x == "software_product" else "Fintech",
    )
    use_screenshots = st.checkbox("Use screenshots", value=False, help="Slower, more tokens, better design classification (fintech only)")
    st.divider()
    st.caption("Input: CSV or domains (one per line)")

# Input
input_mode = st.radio("Input", ["Paste domains", "Upload CSV"], horizontal=True)

df_input = None
if input_mode == "Paste domains":
    raw = st.text_area("Domains (one per line)", placeholder="example.com\ncompany.co.uk\nstartup.io", height=150)
    if raw:
        lines = [l.strip() for l in raw.strip().splitlines() if l.strip()]
        if lines:
            df_input = pd.DataFrame({"Website": lines})
            df_input["Company Name"] = df_input["Website"].apply(
                lambda x: x.lower().replace("https://", "").replace("http://", "").replace("www.", "").rstrip("/").split("/")[0]
            )
            st.info(f"Loaded {len(df_input)} domains")
else:
    uploaded = st.file_uploader("CSV file", type=["csv", "txt"])
    if uploaded:
        try:
            content = uploaded.read().decode("utf-8")
            sep = "\t" if "\t" in content.split("\n")[0] else ","
            df_input = pd.read_csv(io.StringIO(content), sep=sep, dtype=str, engine="python").fillna("")
            if list(df_input.columns) == list(range(len(df_input.columns))) or all(str(c).isdigit() for c in df_input.columns):
                df_input = pd.read_csv(io.StringIO(content), sep=sep, dtype=str, header=None, engine="python").fillna("")
            # Normalize columns
            from main import _normalize_columns
            df_input = _normalize_columns(df_input)
            df_input = df_input[df_input["Company Name"].str.strip() != ""].reset_index(drop=True)
            if "Website" not in df_input.columns:
                st.error("CSV must have Website or URL column")
                df_input = None
            else:
                st.info(f"Loaded {len(df_input)} rows")
        except Exception as e:
            st.error(f"Parse error: {e}")

# Run
if df_input is not None and st.button("Run analysis", type="primary"):
    if not config.ANTHROPIC_API_KEY or not config.JINA_API_KEY:
        st.error("Set ANTHROPIC_API_KEY and JINA_API_KEY in .env")
        st.stop()

    config.PROFILE = profile
    config.USE_SCREENSHOTS = use_screenshots

    with st.spinner("Analyzing..."):
        from analyze import run_analysis
        df_result = run_analysis(df_input, None)

    # Summary
    p = get_profile()
    qk = p["qualify_key"]
    analyzed = df_result[df_result["status"] == "analyzed"]
    unreachable = (df_result["status"] == "unreachable").sum()

    if not analyzed.empty and qk in df_result.columns:
        qualified = analyzed[analyzed[qk].astype(str).str.lower() == "true"]
        not_q = analyzed[analyzed[qk].astype(str).str.lower() == "false"]
        c1, c2, c3 = st.columns(3)
        c1.metric("Qualified", len(qualified))
        c2.metric("Not", len(not_q))
        c3.metric("Unreachable", unreachable)

    st.dataframe(df_result, use_container_width=True, hide_index=True)

    buf = io.StringIO()
    df_result.to_csv(buf, index=False)
    st.download_button("Download CSV", buf.getvalue(), "output.csv", "text/csv")
