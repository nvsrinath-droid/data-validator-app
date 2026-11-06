"""Data quality tier: upload one table, see its profile, review the checks, run them."""
import pandas as pd
import streamlit as st

from core.quality.engine import QualityEngine
from core.quality.profile import profile_file
from core.quality.specs import QualityResult

from ..inputs import resolve_input
from ..quality_grid import CHECK_TYPES, empty_frame, frame_to_specs

STATUS_ICONS = {"pass": "✅", "warn": "⚠️", "fail": "❌", "error": "❌", "inconclusive": "❔"}
STATUS_ORDER = ["pass", "warn", "fail", "inconclusive", "error"]


def _profile_frame(profile) -> pd.DataFrame:
    return pd.DataFrame([{"Column": c.name, "Kind": c.kind.value, "Null %": round(c.null_pct, 2),
                          "Distinct": c.distinct_count, "Bad type": c.nonconforming_count}
                         for c in profile.columns])


def _load_profile(path: str):
    """Profile once per file; a different file clears the checks and results made for the previous one."""
    ss = st.session_state
    if ss.get("quality_path") != path:
        for k in ("quality_checks", "quality_result"):
            ss.pop(k, None)
        ss.quality_profile = profile_file(path)
        ss.quality_path = path
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


def _render_result(result: QualityResult):
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


def render():
    ss = st.session_state
    st.markdown("**🟢 Active Engine:** Data Quality (DuckDB, single table)")
    st.markdown("Upload one table, or give a file path on the server if you are running the app locally.")

    uk = ss.uploader_key
    upload = st.file_uploader("Upload File", type=["csv", "xlsx", "xls"], key=f"qup_{uk}")
    local_path = st.text_input("OR: Local File Path (if running locally)", key=f"qfile_{uk}")
    if not (upload or local_path):
        return
    path = resolve_input(upload, local_path, "quality")
    if not path:
        return
    try:
        profile = _load_profile(path)
    except Exception as e:  # unreadable file, bad Excel, DuckDB parse error: say so, keep the app alive
        ss.pop("quality_path", None)
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

    if st.button("🚀 Run Data Quality Checks", type="primary", key="quality_run",
                 disabled=bool(errors) or not specs):
        with st.spinner("Running checks..."):
            try:
                ss.quality_result = QualityEngine(specs).run(path)
            except Exception as e:
                ss.pop("quality_result", None)
                st.error(f"Could not run the checks: {e}")
    if ss.get("quality_result") is not None:
        _render_result(ss.quality_result)
