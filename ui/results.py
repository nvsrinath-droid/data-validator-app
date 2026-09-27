import io

import pandas as pd
import streamlit as st

from core.reporter import excel_report
from core.results import ComparisonResult


def render_results(res: ComparisonResult, key_prefix: str, title: str = "📊 Validation Results"):
    """Shared results view for every engine (all return a ComparisonResult)."""
    st.subheader(title)
    for w in res.warnings:
        st.warning(w)

    k = st.columns(4)
    k[0].metric("Source Rows", f"{res.total_source:,}")
    k[1].metric("Target Rows", f"{res.total_target:,}")
    k[2].metric("Matched Rows", f"{res.matched_rows:,}")
    k[3].metric("Mismatched Rows", f"{res.mismatched_rows:,}")
    k = st.columns(4)
    k[0].metric("Missing in Target", f"{res.missing_in_target_count:,}")
    k[1].metric("Missing in Source", f"{res.missing_in_source_count:,}")
    k[2].metric("Duplicate Keys", f"{res.duplicate_key_count:,}")
    k[3].metric("Row Count Difference", f"{res.total_source - res.total_target:,}")

    if res.truncated:
        st.info("Row-level detail below is a capped sample; the counts above are exact.")

    if any(res.mismatches_by_column.values()):
        by_col = pd.DataFrame(
            [(c, n) for c, n in res.mismatches_by_column.items() if n], columns=["Column", "Mismatched Rows"])
        st.dataframe(by_col, width="stretch", hide_index=True)

    def to_excel(df, sheet_name):
        buffer = io.BytesIO()
        with pd.ExcelWriter(buffer, engine='openpyxl') as writer:
            df.to_excel(writer, index=False, sheet_name=sheet_name[:31])
        return buffer.getvalue()

    def section(df, base_name, empty_msg, key):
        if df is None or df.empty:
            st.success(empty_msg)
            return
        st.dataframe(df.astype(str), width="stretch", hide_index=True)
        c1, c2 = st.columns(2)
        c1.download_button(f"📥 {base_name} (CSV)", df.to_csv(index=False).encode('utf-8'),
                           file_name=f"{base_name}.csv", mime="text/csv", key=f"{key}_csv", width="stretch")
        c2.download_button(f"📊 {base_name} (Excel)", to_excel(df, base_name), file_name=f"{base_name}.xlsx",
                           mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                           key=f"{key}_xl", width="stretch")

    t1, t2, t3, t4 = st.tabs(["📝 Mismatched Values", "❌ Missing in Target", "❌ Missing in Source", "♊ Duplicate Keys"])
    with t1:
        section(res.mismatches, "Mismatches", "No data mismatches found!", f"{key_prefix}_mm")
    with t2:
        st.caption("Rows in the source (system of record) with no matching key in the target.")
        section(res.missing_in_target, "Missing_in_Target", "Every source row exists in the target.", f"{key_prefix}_mt")
    with t3:
        st.caption("Rows in the target with no matching key in the source.")
        section(res.missing_in_source, "Missing_in_Source", "Every target row exists in the source.", f"{key_prefix}_ms")
    with t4:
        st.caption("Keys that appear more than once on a side. They are excluded from matching.")
        section(res.duplicate_keys, "Duplicate_Keys", "No duplicate primary keys.", f"{key_prefix}_dk")

    st.download_button("📥 Download Full Exceptions Report (Excel)", excel_report(res),
                       file_name="TrueAlign_Validation_Report.xlsx",
                       mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                       type="primary", width="stretch", key=f"{key_prefix}_full")
