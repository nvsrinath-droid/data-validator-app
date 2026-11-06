"""Data quality tier: upload one table, see its profile, review the checks, run them."""
import os

import pandas as pd
import streamlit as st

from ai.agent import AIAgent
from core.quality.engine import QualityEngine
from core.quality.profile import profile_file
from core.quality.report import report_json, results_csv
from core.quality.specs import QualityConfig, QualityResult

from ..components import model_picker
from ..inputs import local_paths_allowed, path_input, resolve_input
from ..quality_grid import CHECK_TYPES, empty_frame, frame_to_specs, non_blank_rows, specs_to_frame

PRIVACY_NOTE = "Only column statistics are sent, no rows."
HEADER_WARNING = ("If your file has no header row, its first row is used as the column names, and column names are "
                  "sent to the AI. Tick **Hide column names** to send placeholders (col_1, col_2, ...) instead.")

STATUS_ICONS = {"pass": "✅", "warn": "⚠️", "fail": "❌", "error": "❌", "inconclusive": "❔"}
STATUS_ORDER = ["pass", "warn", "fail", "inconclusive", "error"]


def _profile_frame(profile) -> pd.DataFrame:
    return pd.DataFrame([{"Column": c.name, "Kind": c.kind.value, "Null %": round(c.null_pct, 2),
                          "Distinct": c.distinct_count, "Bad type": c.nonconforming_count}
                         for c in profile.columns])


def _source_key(path: str):
    """Identity of the file's current contents: a local file edited in place gets a new key."""
    stat = os.stat(path)
    return (path, stat.st_mtime_ns, stat.st_size)


def _load_profile(path: str):
    """Profile once per file version; a different (or changed) file clears everything made for the old one."""
    ss = st.session_state
    key = _source_key(path)
    if ss.get("quality_source") != key:
        for k in ("quality_checks", "quality_result", "quality_explanation", "quality_notes"):
            ss.pop(k, None)
        ss.quality_profile = profile_file(path)
        ss.quality_source = key
    return ss.quality_profile


def _checks_grid(columns):
    ss = st.session_state
    if "quality_checks" not in ss:
        ss.quality_checks = empty_frame()
    st.markdown("Add one row per check. Blank cells use the check's defaults. "
                "`ref_integrity` is not available here; use the command line for it.")
    return st.data_editor(
        ss.quality_checks, num_rows="dynamic", width="stretch", hide_index=True,
        key=f"quality_grid_{ss.config_version}",
        column_config={
            "type": st.column_config.SelectboxColumn("Check", options=CHECK_TYPES, required=True),
            "column": st.column_config.SelectboxColumn("Column", options=list(columns), required=True),
            "severity": st.column_config.SelectboxColumn("Severity", options=["fail", "warn"], default="fail"),
            "max_pct": st.column_config.NumberColumn("Max % (null_rate, type_drift)", min_value=0, max_value=100),
            "unique": st.column_config.CheckboxColumn("Unique (distinct)"),
            "min_distinct": st.column_config.NumberColumn("Min distinct", min_value=0, step=1),
            "max_distinct": st.column_config.NumberColumn("Max distinct", min_value=0, step=1),
            "expected": st.column_config.SelectboxColumn("Expected kind (type_drift)",
                                                         options=["numeric", "date", "string"]),
            "max_age": st.column_config.TextColumn("Max age (freshness)", help="For example 90m, 36h or 2d"),
            "method": st.column_config.SelectboxColumn("Method (outliers)", options=["iqr", "zscore"]),
            "k": st.column_config.NumberColumn("k (outliers)", min_value=0),
            "max_count": st.column_config.NumberColumn("Max outliers", min_value=0, step=1),
        })


def _ai_options():
    """The two privacy switches shared by Suggest and Explain. Both are off by default."""
    c1, c2 = st.columns(2)
    hide = c1.checkbox("Hide column names", value=False, key="quality_hide_names",
                       help="Replace every column name with col_1, col_2, ... before anything is sent.")
    extremes = c2.checkbox("Include extremes", value=False, key="quality_include_extremes",
                           help="Also send each column's min and max (and the freshness age).")
    return hide, extremes


def _suggest_checks(agent: AIAgent, profile, current_rows: pd.DataFrame, hide: bool, extremes: bool):
    """Suggestions are loaded into the grid for review. They are never run from here."""
    ss = st.session_state
    try:
        with st.spinner("Asking the model for check suggestions..."):
            suggested, notes = agent.suggest_checks(profile, include_extremes=extremes, hide_column_names=hide)
    except Exception as e:
        st.error(f"Failed to get suggestions: {e}")
        return
    # Append to the grid exactly as the user has it, so a row with an error is kept for them to fix.
    ss.quality_checks = pd.concat([non_blank_rows(current_rows), specs_to_frame(suggested)], ignore_index=True)
    ss.quality_notes = ([f"Added {len(suggested)} suggested check(s) to the grid. Review them, then run."]
                        + list(notes))
    ss.pop("quality_result", None)
    ss.pop("quality_explanation", None)
    ss.config_version += 1  # a new widget key makes the grid pick up the new rows
    st.rerun()


def _downloads(result: QualityResult, specs):
    c1, c2, c3 = st.columns(3)
    c1.download_button("⬇️ Report (JSON)", report_json(result), "quality_report.json", "application/json",
                       key="quality_dl_json", help="Includes the capped violation samples. Stays on your machine.")
    c2.download_button("⬇️ Results (CSV)", results_csv(result), "quality_results.csv",
                       "text/csv", key="quality_dl_csv")
    if specs:
        c3.download_button("⬇️ Checks (JSON)", QualityConfig(checks=specs).model_dump_json(indent=2, exclude_none=True),
                           "quality_checks.json", "application/json", key="quality_dl_checks",
                           help="Reusable with: python main.py FILE --quality quality_checks.json")


def _render_result(result: QualityResult, specs, agent, hide: bool, extremes: bool):
    st.subheader("📊 Data Quality Results")
    for w in result.warnings:
        st.warning(w)
    counts = {s: sum(1 for r in result.results if r.status == s) for s in STATUS_ORDER}
    counts["fail"] += counts.pop("error")
    cols = st.columns(5)
    cols[0].metric("Rows", f"{result.row_count:,}")
    for col, name in zip(cols[1:], ["pass", "warn", "fail", "inconclusive"]):
        col.metric(f"{STATUS_ICONS[name]} {name.capitalize()}", counts[name])
    for i, r in enumerate(result.results):
        st.markdown(f"{STATUS_ICONS[r.status]} **{r.check.label}** ({r.status}): {r.message}")
        if not r.sample.empty:
            with st.expander(f"Sample of violating rows ({len(r.sample)} shown, {r.violations:,} violations)"):
                st.dataframe(r.sample, width="stretch", hide_index=True)

    _downloads(result, specs)
    if agent is not None:
        st.caption(PRIVACY_NOTE)
        if st.button("🧠 Explain results", key="quality_explain"):
            try:
                with st.spinner("Asking the model to explain the results..."):
                    st.session_state.quality_explanation = agent.explain_results(result, extremes, hide)
            except Exception as e:
                st.error(f"Could not get an explanation: {e}")
    if st.session_state.get("quality_explanation"):
        st.markdown("**Explanation**")
        # Plain text on purpose: the reply is model output, and Markdown would render its links and images.
        st.text(st.session_state.quality_explanation)


def render():
    ss = st.session_state
    st.markdown("**🟢 Active Engine:** Data Quality (DuckDB, single table)")
    st.markdown("Upload one table" + (", or give a file path on the server." if local_paths_allowed() else "."))

    uk = ss.uploader_key
    upload = st.file_uploader("Upload File", type=["csv", "xlsx", "xls"], key=f"qup_{uk}")
    local_path = path_input("OR: Local File Path (if running locally)", f"qfile_{uk}")
    if not (upload or local_path):
        return
    path = resolve_input(upload, local_path, "quality")
    if not path:
        return
    try:
        profile = _load_profile(path)
    except Exception as e:  # unreadable file, bad Excel, DuckDB parse error: say so, keep the app alive
        ss.pop("quality_source", None)
        st.error(f"Could not read the file: {e}")
        return

    st.subheader("🔎 Profile")
    st.caption(f"{profile.row_count:,} rows, {len(profile.columns)} columns")
    st.dataframe(_profile_frame(profile), width="stretch", hide_index=True)

    st.subheader("✅ Checks")
    edited = _checks_grid([c.name for c in profile.columns])
    specs, errors = frame_to_specs(edited, [c.name for c in profile.columns])
    for msg in errors:
        st.error(msg)

    st.markdown("#### 🧠 AI assistance (optional)")
    agent = model_picker("quality")
    hide, extremes = _ai_options()
    if agent is not None:
        st.caption(PRIVACY_NOTE)
        if not hide:
            st.warning(HEADER_WARNING)
        if st.button("✨ Suggest checks", key="quality_suggest"):
            _suggest_checks(agent, profile, edited, hide, extremes)
    for note in ss.get("quality_notes", []):
        st.info(note)

    if st.button("🚀 Run Data Quality Checks", type="primary", key="quality_run",
                 disabled=bool(errors) or not specs):
        ss.pop("quality_explanation", None)
        ss.pop("quality_notes", None)
        with st.spinner("Running checks..."):
            try:
                ss.quality_result = QualityEngine(specs).run(path)
            except Exception as e:
                ss.pop("quality_result", None)
                st.error(f"Could not run the checks: {e}")
    if ss.get("quality_result") is not None:
        _render_result(ss.quality_result, specs, agent, hide, extremes)
