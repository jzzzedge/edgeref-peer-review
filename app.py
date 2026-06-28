# -*- coding: utf-8 -*-
"""EdgeRef AI Pre-submission Review --- Streamlit App."""

import hashlib
import hmac
import json
import os

import pandas as pd
import streamlit as st

from utils.ai_client import generate_ai_review
from utils.file_cache import (
    get_uploaded_file_signature,
    get_uploaded_files_signature,
    has_manuscript_changed,
    has_source_data_changed,
)
from utils.file_handler import get_files_summary
from utils.manuscript_parser import parse_manuscript
from utils.prompt_builder import build_review_prompt
from utils.report_exporter import (
    build_report_metadata,
    export_docx_report,
    export_markdown_report,
)
from utils.review_engine import generate_mock_review
from utils.source_data_parser import parse_source_data
from utils.preflight_checker import run_preflight_check
from utils.journal_profile import build_journal_profile
from utils.language_detector import detect_manuscript_language
from utils.journal_database import (
    load_journal_database,
    match_chinese_core_journal,
    get_journal_match_summary,
    get_catalog_stats,
    clear_catalog_cache,
)
from utils.health_check import run_health_check

# ---------------------------------------------------------------------------
# Page config
# ---------------------------------------------------------------------------
st.set_page_config(
    page_title="EdgeRef AI Pre-submission Review",
    page_icon="\U0001f4dd",
    layout="wide",
)

st.title("\U0001f4dd EdgeRef AI Pre-submission Review")
st.info(
    "This system provides AI-assisted pre-submission review for academic manuscripts. "
    "It does not replace formal journal peer review."
)

# ---------------------------------------------------------------------------
# Backend configuration (never displayed to users)
# ---------------------------------------------------------------------------
engine_mode = "EdgeRef AI Review"
show_prompt = False

def _resolve_config():
    """Resolve API key and model from st.secrets or env vars (never displayed)."""
    try:
        api_key = st.secrets.get("DEEPSEEK_API_KEY") or os.environ.get("DEEPSEEK_API_KEY")
    except Exception:
        api_key = os.environ.get("DEEPSEEK_API_KEY")
    try:
        model = st.secrets.get("DEEPSEEK_MODEL") or os.environ.get("DEEPSEEK_MODEL", "deepseek-v4-flash")
    except Exception:
        model = os.environ.get("DEEPSEEK_MODEL", "deepseek-v4-flash")
    return api_key, model

_deepseek_api_key, _deepseek_model = _resolve_config()
_edgeref_debug = os.environ.get("EDGEREF_DEBUG", "").lower() == "true"
_edgeref_enable_mock = os.environ.get("EDGEREF_ENABLE_MOCK", "").lower() == "true"
_edgeref_access_code = None

def _resolve_access_code():
    """Resolve access code from st.secrets or env vars (never displayed)."""
    try:
        return st.secrets.get("EDGEREF_ACCESS_CODE") or os.environ.get("EDGEREF_ACCESS_CODE")
    except Exception:
        return os.environ.get("EDGEREF_ACCESS_CODE")

_edgeref_access_code = _resolve_access_code()

# ---------------------------------------------------------------------------
# Sidebar
# ---------------------------------------------------------------------------
with st.sidebar:
    st.header("\u2699\ufe0f Settings")

    if _edgeref_enable_mock:
        engine_mode = st.radio(
            "Review Engine",
            ["Mock Report", "EdgeRef AI Review"],
            index=1,
            key="engine_mode",
        )
    else:
        engine_mode = "EdgeRef AI Review"
        st.session_state["engine_mode"] = engine_mode

    if _edgeref_debug:
        show_prompt = st.checkbox(
            "Show internal review prompt",
            value=False,
            key="show_prompt",
        )
        st.markdown("---")
        with st.expander("\U0001f52d Health Check", expanded=False):
            try:
                _hc = run_health_check()
                _hc_status_icon = "\u2705" if _hc["status"] == "Pass" else "\u26a0\ufe0f"
                st.markdown(f"**Status**: {_hc_status_icon} {_hc['status']}")
                for _chk in _hc["checks"]:
                    _icon = "\u2705" if _chk["passed"] else "\u274c"
                    st.markdown(f"{_icon} **{_chk['name']}**: {_chk['detail']}")
                if _hc["suggested_actions"]:
                    st.markdown("**Suggested actions:**")
                    for _a in _hc["suggested_actions"]:
                        st.markdown(f"- {_a}")
            except Exception:
                st.warning("Health check unavailable")

    access_code_verified = True
    if _edgeref_access_code:
        st.markdown("---")
        access_code_input = st.text_input("Access code", type="password")
        access_code_verified = bool(access_code_input) and hmac.compare_digest(
            access_code_input, _edgeref_access_code
        )

# ---------------------------------------------------------------------------
# Session state initialization
# ---------------------------------------------------------------------------
# Cache journal database across reruns (Streamlit Cloud friendly)
@st.cache_data(ttl=3600)
def _cached_load_journal_database():
    """Load journal database once per TTL window. Wraps @lru_cache for Streamlit."""
    return load_journal_database()


for _key in (
    "report_text",
    "report_metadata",
    "settings_hash",
    "parsed_manuscript",
    "parsed_source_data",
    "preflight_result",
    "manuscript_signature",
    "source_data_signature",
    "files_processed",
):
    if _key not in st.session_state:
        st.session_state[_key] = None


def _get_settings_hash(review_mode_value=None, journal_profile_value=None):
    """Compute a hash of report-affecting settings without storing API keys."""
    profile = journal_profile_value or globals().get("journal_profile") or {}
    raw = json.dumps(
        {
            "review_mode": review_mode_value or st.session_state.get("review_mode", ""),
            "target_journal": profile.get("journal_name", ""),
            "subject_area": profile.get("subject_area", ""),
            "article_type": profile.get("article_type", ""),
            "journal_scope": profile.get("journal_scope", ""),
            "special_requirements": profile.get("special_requirements", ""),
            "word_limit": profile.get("word_limit", ""),
            "figure_limit": profile.get("figure_limit", ""),
            "table_limit": profile.get("table_limit", ""),
            "reference_limit": profile.get("reference_limit", ""),
        },
        sort_keys=True,
        ensure_ascii=False,
    )
    return hashlib.md5(raw.encode()).hexdigest()


# ---------------------------------------------------------------------------
# Step 1. Upload Manuscript
# ---------------------------------------------------------------------------
st.markdown("---")
st.markdown("## **Step 1. \U0001f4c4 Upload Manuscript**")

manuscript_file = st.file_uploader(
    "Support PDF/DOCX/TXT",
    type=["pdf", "docx", "txt"],
    accept_multiple_files=False,
    key="manuscript",
    label_visibility="collapsed",
)

if manuscript_file:
    st.info(f"Uploaded: **{manuscript_file.name}** ({manuscript_file.size:,} bytes)")
else:
    with st.expander("\U0001f4d6 What files are supported?"):
        st.markdown("""
        - **PDF**: Scientific manuscripts in PDF format. *Scanned/image-only PDFs may fail.*
        - **DOCX**: Microsoft Word documents
        - **TXT**: Plain text files
        - For first-time testing, use a copyable-text PDF, DOCX, or TXT.
        - Large source data files may increase parsing time.
        - Uploaded files are processed temporarily and are **not** saved to disk.
        """)
    st.caption("\U0001f4a1 First-time testing? Use a copyable-text PDF / DOCX / TXT. Scanned PDFs may fail. Source data is processed temporarily and not saved to disk.")

# ---------------------------------------------------------------------------
# Step 2. Upload Source Data
# ---------------------------------------------------------------------------
st.markdown("---")
st.markdown("## **Step 2. \U0001f4e6 Upload Source Data** *(Optional)*")

source_data_files = st.file_uploader(
    "Supports CSV, XLSX, ZIP (multiple files)",
    type=["csv", "xlsx", "zip"],
    accept_multiple_files=True,
    key="source_data",
    label_visibility="collapsed",
)

if source_data_files:
    st.info(f"{len(source_data_files)} file(s) uploaded")
    source_data_info = get_files_summary(source_data_files)
    st.dataframe(source_data_info, use_container_width=True)
else:
    st.caption("No source data uploaded. Review will be based on manuscript text only. This step can be skipped.")

# ---------------------------------------------------------------------------
# File Processing
# ---------------------------------------------------------------------------
st.markdown("---")
st.markdown("## **\U0001f4cb File Processing**")

processing_needed = False
files_changed_warning = False

# Invalidate cached parsed results if the uploaded files no longer match the
# last processed signatures. This keeps review generation from using stale
# manuscript/source-data results after files are replaced, added, or removed.
if st.session_state.get("files_processed"):
    current_manuscript_signature = get_uploaded_file_signature(manuscript_file) if manuscript_file else None
    current_source_data_signature = get_uploaded_files_signature(source_data_files or [])
    cache_mismatch = (
        current_manuscript_signature != st.session_state.get("manuscript_signature")
        or current_source_data_signature != st.session_state.get("source_data_signature")
    )
    if cache_mismatch:
        st.session_state["report_text"] = None
        st.session_state["report_metadata"] = None
        st.session_state["settings_hash"] = None
        st.session_state["parsed_manuscript"] = None
        st.session_state["parsed_source_data"] = None
        st.session_state["preflight_result"] = None
        st.session_state["files_processed"] = None
        files_changed_warning = True
        st.warning("Uploaded files changed. Please process files again before generating a new report.")

if not manuscript_file:
    st.info("Please upload a manuscript in Step 1 before processing files.")
else:
    # Determine if processing is needed
    already_processed = st.session_state.get("files_processed")
    if already_processed:
        msig = st.session_state.get("manuscript_signature")
        ssig = st.session_state.get("source_data_signature")
        ms_changed = has_manuscript_changed(manuscript_file, msig)
        sd_changed = has_source_data_changed(source_data_files or [], ssig)
        if ms_changed or sd_changed:
            processing_needed = True
            files_changed_warning = True
        else:
            processing_needed = False
    else:
        processing_needed = True

    if not st.session_state.get("files_processed"):
        st.info(
            "Files are parsed only when you click the button below. "
            "Changing review mode, journal information, access code, or download buttons will not reprocess files."
        )

    button_label = "Reprocess files" if already_processed and not files_changed_warning else "Process uploaded files"
    process_btn = st.button(button_label, type="primary", use_container_width=True)

    if process_btn:
        # Parse manuscript
        with st.status("Processing manuscript...", expanded=False):
            parsed = parse_manuscript(manuscript_file)
            st.session_state["parsed_manuscript"] = parsed
            st.session_state["manuscript_signature"] = get_uploaded_file_signature(manuscript_file)

        # Parse source data
        parsed_sd = []
        if source_data_files:
            with st.status("Processing source data...", expanded=False):
                parsed_sd = parse_source_data(source_data_files)
        st.session_state["parsed_source_data"] = parsed_sd
        st.session_state["source_data_signature"] = get_uploaded_files_signature(source_data_files or [])

        # Run preflight check
        pf = run_preflight_check(
            st.session_state["parsed_manuscript"],
            st.session_state["parsed_source_data"],
        )
        st.session_state["preflight_result"] = pf
        st.session_state["files_processed"] = True
        processing_needed = False

    # Show parsing results if available
    cached_ms = st.session_state.get("parsed_manuscript")
    cached_sd = st.session_state.get("parsed_source_data")

    if st.session_state.get("files_processed") and cached_ms:
        # Manuscript parse result
        if cached_ms.get("parse_status") == "failed":
            st.error(f"\u274c Manuscript parse failed: {cached_ms.get('error_message', 'unknown error')}")
        else:
            st.success(
                f"\u2705 Manuscript parsed: **{cached_ms['file_name']}** "
                f"({cached_ms['char_count']:,} chars, {cached_ms['word_count']:,} words, "
                f"{len(cached_ms['detected_sections'])} sections)"
            )

        # Source data parse result
        if cached_sd:
            sc = sum(1 for x in cached_sd if x.get("parse_status") == "success")
            fc = len(cached_sd) - sc
            if sc > 0:
                st.success(f"\u2705 Source data parsed: {len(cached_sd)} file(s), {sc} successful")
            if fc > 0:
                st.warning(f"\u26a0\ufe0f {fc} file(s) failed parsing")
        else:
            st.info("Source data: Not uploaded")

        # Preflight result
        pf_res = st.session_state.get("preflight_result", {})
        if pf_res:
            st.info(
                f"**Preflight**: {pf_res.get('overall_status', 'N/A')} "
                f"(Risk: {pf_res.get('risk_score', '?')}/100)"
            )

# ---------------------------------------------------------------------------
# File Processing Status
# ---------------------------------------------------------------------------
st.markdown("---")
st.markdown("### **\U0001f4ca File Processing Status**")

ms_status = "Not uploaded"
sd_status = "Not uploaded"
pf_status = "Not ready"
review_ready = "Needs file processing"
manuscript_lang = None
review_output_lang = None

if manuscript_file:
    ms_status = "Uploaded"
    cached_ms = st.session_state.get("parsed_manuscript")
    if cached_ms and st.session_state.get("files_processed"):
        if cached_ms.get("parse_status") == "failed":
            ms_status = "Parse failed"
        else:
            ms_status = "Parsed successfully"

if source_data_files:
    sd_status = "Uploaded"
    cached_sd = st.session_state.get("parsed_source_data")
    if cached_sd and st.session_state.get("files_processed"):
        sc = sum(1 for x in cached_sd if x.get("parse_status") == "success")
        fc = len(cached_sd) - sc
        if fc > 0 and sc > 0:
            sd_status = "Partially failed"
        elif fc > 0:
            sd_status = "Parse failed"
        else:
            sd_status = "Parsed successfully"

if st.session_state.get("files_processed") and st.session_state.get("preflight_result"):
    pf_status = "Ready"

if (
    st.session_state.get("files_processed")
    and ms_status == "Parsed successfully"
    and (sd_status in ("Parsed successfully", "Partially failed", "Not uploaded") or not source_data_files)
):
    review_ready = "Ready for AI review"

col_s1, col_s2, col_s3, col_s4 = st.columns(4)
with col_s1:
    if "failed" in ms_status:
        st.error(f"**Manuscript**: {ms_status}")
    elif "success" in ms_status:
        st.success(f"**Manuscript**: {ms_status}")
    elif ms_status != "Not uploaded":
        st.warning(f"**Manuscript**: {ms_status}")
    else:
        st.info(f"**Manuscript**: {ms_status}")
with col_s2:
    if "failed" in sd_status:
        st.error(f"**Source Data**: {sd_status}")
    elif "success" in sd_status:
        st.success(f"**Source Data**: {sd_status}")
    elif sd_status != "Not uploaded":
        st.warning(f"**Source Data**: {sd_status}")
    else:
        st.info(f"**Source Data**: {sd_status}")
with col_s3:
    if pf_status == "Ready":
        st.success(f"**Preflight**: {pf_status}")
    else:
        st.info(f"**Preflight**: {pf_status}")
with col_s4:
    if review_ready == "Ready for AI review":
        st.success(f"\u2705 {review_ready}")
    else:
        st.warning(f"\u26a0\ufe0f {review_ready}")

# ---------------------------------------------------------------------------
# Step 3. Target Journal Profile
# ---------------------------------------------------------------------------
st.markdown("---")
st.markdown("## **Step 3. \U0001f3af Target Journal Profile** *(Optional)*")

with st.expander("Fill Target Journal Profile", expanded=False):
    col_j1, col_j2 = st.columns(2)
    with col_j1:
        jp_name = st.text_input("Journal Name", key="jp_name")
        jp_subject = st.text_input("Subject Area", key="jp_subject")
        jp_type = st.selectbox(
            "Article Type",
            [
                "",
                "Original Research Article",
                "Review Article",
                "Short Communication",
                "Case Report",
                "Methods Article",
                "Other",
            ],
            key="jp_type",
        )
    with col_j2:
        jp_words = st.text_input("Word Limit (optional)", key="jp_words")
        jp_fig = st.text_input("Figure Limit (optional)", key="jp_fig")
        jp_table = st.text_input("Table Limit (optional)", key="jp_table")
        jp_ref = st.text_input("Reference Limit (optional)", key="jp_ref")
    jp_scope = st.text_area("Journal Scope / Aims (optional)", key="jp_scope", height=80)
    jp_special = st.text_area("Special Requirements (optional)", key="jp_special", height=60)

journal_profile = build_journal_profile(
    journal_name=jp_name,
    subject_area=jp_subject,
    article_type=jp_type,
    journal_scope=jp_scope,
    word_limit=jp_words,
    figure_limit=jp_fig,
    table_limit=jp_table,
    reference_limit=jp_ref,
    special_requirements=jp_special,
)

if journal_profile:
    summary_parts = []
    if jp_name:
        summary_parts.append(f"Journal: {jp_name}")
    if jp_subject:
        summary_parts.append(f"Subject: {jp_subject}")
    if jp_type:
        summary_parts.append(f"Type: {jp_type}")
    st.info(f"Target journal info filled: {' | '.join(summary_parts)}")
    # Display catalog status
    try:
        _cat_stats = get_catalog_stats()
        if _cat_stats.get("total_records") and _cat_stats["total_records"] > 0:
            st.caption(f"Journal catalog loaded: {_cat_stats['total_records']:,} records")
        elif _cat_stats.get("warning"):
            st.caption(_cat_stats["warning"])
    except Exception:
        pass
    if jp_name:
        match_result = match_chinese_core_journal(jp_name, _cached_load_journal_database())
        with st.expander("\U0001f50d Journal Catalog Match", expanded=False):
            st.markdown(get_journal_match_summary(match_result))
else:
    st.info("No target journal info provided. Review will be general.")

# ---------------------------------------------------------------------------
# Step 4. Preflight Check
# ---------------------------------------------------------------------------
st.markdown("---")
st.markdown("## **Step 4. \U0001f6f8 Preflight Check**")

cached_pf = st.session_state.get("preflight_result")
cached_ms = st.session_state.get("parsed_manuscript")

if not st.session_state.get("files_processed") or not cached_ms:
    st.warning("Please process files first (see File Processing section above).")
elif not cached_pf:
    st.warning("Preflight not yet available. Process files first.")
else:
    pf_result = cached_pf
    if cached_ms.get("parse_status") == "failed":
        st.error("Manuscript parsing failed. Preflight Check set to High Risk.")
    elif not cached_ms.get("full_text", "").strip():
        st.warning("No text content extracted. Check if the file is readable.")

    status_icon = {"Pass": "\u2705", "Warning": "\u26a0\ufe0f", "High Risk": "\u274c"}
    icon = status_icon.get(pf_result["overall_status"], "\u2753")
    st.markdown(
        f"**Status**: {icon} {pf_result['overall_status']} "
        f"| **Risk Score**: {pf_result['risk_score']}/100"
    )

    if pf_result["key_warnings"]:
        st.markdown("**Warnings**:")
        for w in pf_result["key_warnings"][:5]:
            st.markdown(f"- {w}")

    if pf_result["suggested_actions"]:
        st.markdown("**Suggested Actions**:")
        for a in pf_result["suggested_actions"][:3]:
            st.markdown(f"- \U0001f449 {a}")

    with st.expander("\U0001f50d Detailed Checks"):
        st.markdown("**Manuscript Checks**")
        for c in pf_result["manuscript_checks"]:
            status_sym = (
                "\u2705"
                if c["status"] == "Pass"
                else ("\u26a0\ufe0f" if c["status"] == "Warning" else "\u274c")
            )
            st.markdown(f"{status_sym} {c['check']}: {c['detail']}")
        st.divider()
        st.markdown("**Source Data Checks**")
        for c in pf_result["source_data_checks"]:
            status_sym = (
                "\u2705"
                if c["status"] == "Pass"
                else ("\u26a0\ufe0f" if c["status"] == "Warning" else "\u274c")
            )
            st.markdown(f"{status_sym} {c['check']}: {c['detail']}")

# ---------------------------------------------------------------------------
# Current Input Summary
# ---------------------------------------------------------------------------
st.markdown("---")
st.markdown("## **\U0001f4cb Current Input Summary**")

summary_data = {}
if manuscript_file:
    summary_data["Manuscript"] = manuscript_file.name
else:
    summary_data["Manuscript"] = "Not uploaded"
if source_data_files:
    summary_data["Source Data"] = f"{len(source_data_files)} file(s)"
else:
    summary_data["Source Data"] = "None"
if journal_profile:
    summary_data["Target Journal"] = (
        journal_profile.get("journal_name")
        or journal_profile.get("subject_area")
        or "Filled (partial)"
    )
else:
    summary_data["Target Journal"] = "Not specified"
summary_data["Review Engine"] = engine_mode
if st.session_state.get("files_processed") and st.session_state.get("preflight_result"):
    summary_data["Preflight Status"] = st.session_state["preflight_result"].get("overall_status", "N/A")
else:
    summary_data["Preflight Status"] = "Not ready"
summary_data["Files Processed"] = "Yes" if st.session_state.get("files_processed") else "No"
cached_ms = st.session_state.get("parsed_manuscript")
if cached_ms and st.session_state.get("files_processed"):
    summary_data["Manuscript Language"] = cached_ms.get("detected_language", "N/A")
    summary_data["Review Output Language"] = cached_ms.get("output_language", "N/A")
else:
    summary_data["Manuscript Language"] = "N/A"
    summary_data["Review Output Language"] = "N/A"

col_s1, col_s2, col_s3 = st.columns(3)
with col_s1:
    for label in ("Manuscript", "Source Data", "Target Journal", "Manuscript Language", "Review Output Language"):
        st.markdown(f"**{label}**: {summary_data.get(label, '')}")
with col_s2:
    st.markdown(f"**Review Engine**: {summary_data.get('Review Engine', '')}")
with col_s3:
    st.markdown(f"**Preflight Status**: {summary_data.get('Preflight Status', '')}")
    st.markdown(f"**Files Processed**: {summary_data.get('Files Processed', '')}")

# ---------------------------------------------------------------------------
# Prompt display (debug mode only)
# ---------------------------------------------------------------------------
if (
    show_prompt
    and manuscript_file
    and st.session_state.get("files_processed")
    and st.session_state.get("parsed_manuscript")
    and "review_mode" in st.session_state
):
    prompt_text = build_review_prompt(
        mode=st.session_state["review_mode"],
        parsed_manuscript=st.session_state["parsed_manuscript"],
        parsed_source_data=st.session_state.get("parsed_source_data", []),
        journal_profile=journal_profile,
    )
    with st.expander("\U0001f916 Review Prompt", expanded=True):
        st.code(prompt_text, language="markdown")

# ---------------------------------------------------------------------------
# Step 5. Generate Peer Review Report
# ---------------------------------------------------------------------------
st.markdown("---")
st.markdown("## **Step 5. \U0001f680 Generate Peer Review Report**")

review_mode = st.radio(
    "Select Review Mode",
    options=[
        "\u7f16\u8f91\u521d\u5ba1",
        "\u540c\u884c\u4e13\u5bb6\u8bc4\u5ba1",
        "\u7edf\u8ba1\u4e0e\u65b9\u6cd5\u5b66\u5ba1\u67e5",
        "\u6570\u636e\u5b8c\u6574\u6027\u5ba1\u67e5",
        "\u7efc\u5408\u9884\u8bc4\u5ba1",
    ],
    index=0,
    key="review_mode",
)

# Settings change detection
current_hash = _get_settings_hash(review_mode, journal_profile)
settings_changed = (
    st.session_state.get("settings_hash") is not None
    and st.session_state["settings_hash"] != current_hash
)
if settings_changed and st.session_state.get("report_text"):
    st.warning(
        "Review mode or target journal information has changed. "
        "Please click the button below to regenerate the report."
    )

generate_btn = st.button(
    "\U0001f680 Generate Review Report", type="primary", use_container_width=True
)

# --- Generate report ---
if generate_btn:
    if not manuscript_file:
        st.error("Please upload a manuscript file first.")
        st.stop()

    if not st.session_state.get("files_processed"):
        st.error("Please process files first (see File Processing section above).")
        st.stop()

    cached_ms = st.session_state.get("parsed_manuscript")
    cached_sd = st.session_state.get("parsed_source_data", [])
    pf_res = st.session_state.get("preflight_result")

    if engine_mode == "Mock Report":
        if cached_ms and cached_ms.get("parse_status") == "failed":
            st.warning("Manuscript parsing failed. Mock report is for workflow testing only.")
        st.success("Generating mock report...")
        ms_info = get_files_summary([manuscript_file])
        sd_info = get_files_summary(source_data_files) if source_data_files else []
        report = generate_mock_review(
            mode=review_mode,
            manuscript_info=ms_info,
            source_data_info=sd_info,
            parsed_source_data=cached_sd,
            parsed_manuscript=cached_ms,
            journal_profile=journal_profile,
        )
        st.success("Mock report generated.")
    else:
        if not _deepseek_api_key:
            st.error("AI review service is not configured. Please contact the administrator.")
            st.stop()
        if cached_ms and cached_ms.get("parse_status") == "failed":
            st.error("Manuscript parsing failed. AI review cannot proceed.")
            st.stop()
        if not access_code_verified:
            st.error("Invalid access code. Please contact the administrator.")
            st.stop()
        with st.spinner("Generating EdgeRef AI review report..."):
            prompt_text = build_review_prompt(
                mode=review_mode,
                parsed_manuscript=cached_ms,
                parsed_source_data=cached_sd,
                journal_profile=journal_profile,
            )
            result = generate_ai_review(
                prompt=prompt_text,
                model=_deepseek_model,
                api_key=_deepseek_api_key,
            )
        if result["status"] == "error":
            st.error(f"{result['error']}")
            st.stop()
        report = result["text"]
        if report and report.strip():
            st.success("AI review report generated.")
        else:
            st.warning("AI returned empty content. Please try again.")

    engine_display = "EdgeRef AI Review Engine" if engine_mode != "Mock Report" else "Mock Report"
    ms_lang = (cached_ms or {}).get("detected_language")
    ms_output_lang = (cached_ms or {}).get("output_language")
    jp_name_for_match = (journal_profile or {}).get("journal_name", "")
    journal_match_result = match_chinese_core_journal(jp_name_for_match, _cached_load_journal_database()) if jp_name_for_match else None
    metadata = build_report_metadata(
        mode=review_mode,
        engine=engine_display,
        journal_profile=journal_profile,
        manuscript_language=ms_lang,
        review_output_language=ms_output_lang,
        journal_match=journal_match_result,
    )
    st.session_state["report_text"] = report
    st.session_state["report_metadata"] = metadata
    st.session_state["settings_hash"] = current_hash

# --- Display report ---
if st.session_state.get("report_text") and st.session_state.get("report_metadata"):
    report = st.session_state["report_text"]
    metadata = st.session_state["report_metadata"]

    st.divider()
    st.markdown(report)

    markdown_bytes = export_markdown_report(report, metadata)
    docx_buffer = export_docx_report(report, metadata)

    c1, c2 = st.columns(2)
    with c1:
        st.download_button(
            label="\U0001f4e5 Download Markdown Report",
            data=markdown_bytes,
            file_name=f"pre_review_report_{metadata['timestamp']}.md",
            mime="text/markdown",
            use_container_width=True,
        )
    with c2:
        st.download_button(
            label="\U0001f4c4 Download Word Report",
            data=docx_buffer.getvalue(),
            file_name=f"pre_review_report_{metadata['timestamp']}.docx",
            mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            use_container_width=True,
        )

# ---------------------------------------------------------------------------
# Footer
# ---------------------------------------------------------------------------
st.markdown("---")
st.caption("Generated by EdgeRef")
