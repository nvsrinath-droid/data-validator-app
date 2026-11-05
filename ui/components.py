"""Widgets shared by all three tiers."""
from typing import Optional, Tuple

import pandas as pd
import streamlit as st

from ai.agent import AIAgent, resolve_rules
from core.db import DB_TYPES, DEFAULT_PORTS, MSSQL_DRIVERS, build_url, default_mssql_driver, installed_mssql_drivers
from core.sources import DataPair
from core.templates import (PREVIEW_COL, RULE_COL, SOURCE_COL, TARGET_COL, config_from_grid, config_to_grid,
                            manual_config, preview_is_stale, read_template, template_bytes, with_rule_preview)

from .results import render_results
from .state import AVAILABLE_MODELS, reset_app, set_config


def render_connection_fields(key_prefix: str, label: str = "Database Type"):
    """Database connection inputs. Returns a SQLAlchemy URL (password masked when printed) or None."""
    db_type = st.selectbox(label, DB_TYPES, key=f"db_type_{key_prefix}")
    if db_type == "SQLite (Local)":
        db_path = st.text_input("Database File Path", placeholder="samples/local_production.db", key=f"sqlite_{key_prefix}")
        return build_url(db_type, sqlite_path=db_path) if db_path else None

    c1, c2 = st.columns([3, 1])
    host_hint = "e.g., my-account (or my-account.snowflakecomputing.com)" if db_type == "Snowflake" else "e.g., db.example.com"
    host = c1.text_input("Host / Server Address", placeholder=host_hint, key=f"host_{key_prefix}")
    port = c2.text_input("Port", value=DEFAULT_PORTS[db_type], key=f"port_{key_prefix}")
    db_hint = {"Oracle": "Service name, e.g., ORCLPDB1", "Snowflake": "DATABASE or DATABASE/SCHEMA"}.get(db_type, "")
    db_name = st.text_input("Database Name", placeholder=db_hint, key=f"db_{key_prefix}")
    c3, c4 = st.columns(2)
    user = c3.text_input("Username", key=f"user_{key_prefix}")
    password = c4.text_input("Password", type="password", key=f"pass_{key_prefix}")

    mssql = {}
    if db_type == "Microsoft SQL Server":
        c5, c6 = st.columns([3, 2])
        drivers = list(dict.fromkeys(MSSQL_DRIVERS + installed_mssql_drivers()))
        mssql["mssql_driver"] = c5.selectbox("ODBC Driver", drivers, index=drivers.index(default_mssql_driver()),
                                             key=f"driver_{key_prefix}",
                                             help="Driver 18 encrypts connections by default.")
        c6.markdown("<div style='height: 30px;'></div>", unsafe_allow_html=True)
        mssql["trust_server_certificate"] = c6.checkbox(
            "Trust server certificate", key=f"trust_{key_prefix}",
            help="Needed with Driver 18 when the server uses a self-signed certificate (common on-prem).")

    if host and db_name and user and password:
        try:
            return build_url(db_type, host, port, db_name, user, password, **mssql)
        except ValueError:
            st.error("Port must be a number.")
    return None


def render_sql_form(key_prefix: str) -> Optional[dict]:
    url = render_connection_fields(key_prefix)
    query = st.text_area("SQL Query", placeholder="SELECT * FROM table_name", key=f"q_{key_prefix}")
    if url is not None and query:
        return {"type": "sql", "url": url, "query": query}
    return None


def model_picker(key: str) -> Optional[AIAgent]:
    """Returns an agent for the selected model, or None if no usable model/key is configured."""
    models = st.session_state.user_configured_models
    if not models:
        st.info("ℹ️ No AI model configured. Use ⚙️ Settings (top right) to add one, or map columns "
                "manually / from a template below.")
        return None
    c_model, _ = st.columns([1, 2])
    with c_model:
        display = st.selectbox("Active AI Model", models, key=f"{key}_model")
    model, key_name = AVAILABLE_MODELS[display]
    api_key = st.session_state.stored_keys.get(key_name, "")
    if not api_key:
        st.warning(f"⚠️ Add your `{key_name}` in ⚙️ Settings (top right) to use {display}.")
        return None
    return AIAgent(model_name=model, api_key=api_key)


def _columns(pair: DataPair, side: str) -> list:
    """Column names per input set, cached so pushdown doesn't re-query the database on every rerun."""
    cache = st.session_state.setdefault("column_cache", {})
    if (pair.signature, side) not in cache:
        cache[(pair.signature, side)] = pair.columns(side)
    return cache[(pair.signature, side)]


def _mapping_sources(pair: DataPair, key: str, agent: Optional[AIAgent]):
    tab_ai, tab_template, tab_manual = st.tabs(["✨ Auto-Map with AI", "📥 Load Saved Template", "🛠️ Manual Mapping"])

    with tab_ai:
        st.markdown("<div style='margin-bottom: 10px; color: #cbd5e1;'>Let our AI analyze a 5-row sample of each side and resolve schema differences.</div>", unsafe_allow_html=True)
        if st.button("✨ Auto-Map with AI", type="primary", width="stretch", key=f"{key}_ai", disabled=agent is None):
            with st.spinner("Reading a sample of your data and building a mapping schema..."):
                try:
                    sample1 = pair.sample("source", 5).to_csv(index=False)
                    sample2 = pair.sample("target", 5).to_csv(index=False)
                    set_config(agent.suggest_configuration(sample1, sample2))
                    st.success("AI Analysis Complete!")
                except Exception as e:
                    st.error(f"Error during AI analysis: {pair.redact(str(e))}")

    with tab_template:
        if st.session_state.is_guest:
            st.info("🔒 Log in to a free account to load saved mapping templates.")
        else:
            st.markdown("<div style='margin-bottom: 10px; color: #cbd5e1;'>Bypass the AI and instantly load a previously saved configuration file.</div>", unsafe_allow_html=True)
            template_file = st.file_uploader("Upload Mapping Template", type=["csv", "xlsx"], label_visibility="collapsed",
                                             key=f"{key}_tpl_{st.session_state.uploader_key}")
            if template_file and st.session_state.get(f"{key}_tpl_loaded") != template_file.file_id:
                try:
                    set_config(read_template(template_file), from_template=True)
                    st.session_state[f"{key}_tpl_loaded"] = template_file.file_id
                    st.success("Template Loaded Successfully! Primary Keys and Mappings restored.")
                except Exception as e:
                    st.error(f"Failed to load template: {e}")

    with tab_manual:
        st.markdown("<div style='margin-bottom: 10px; color: #cbd5e1;'>Bypass the AI and templates entirely. Columns with the same name are paired for you.</div>", unsafe_allow_html=True)
        if st.button("🛠️ Setup Manual Mappings", width="stretch", key=f"{key}_manual"):
            try:
                set_config(manual_config(_columns(pair, "source"), _columns(pair, "target")))
                st.success("Manual Mapping Grid Ready!")
            except Exception as e:
                st.error(f"Could not read columns: {pair.redact(str(e))}")


def _mapping_editor(pair: DataPair, key: str, file_slug: str) -> Tuple[list, pd.DataFrame, dict]:
    config = st.session_state.ai_config
    source_cols, target_cols = _columns(pair, "source"), _columns(pair, "target")

    if st.session_state.get("is_template_loaded"):
        st.write("Review your loaded template mappings before running the comparison:")
    else:
        st.write("Review and adjust the mapping before running the comparison:")

    st.markdown("**Primary Keys** (the unique identifier that links rows together)")
    pk_cols = st.multiselect("Select Primary Keys (Source Columns)", options=source_cols,
                             default=[k for k in config.primary_keys if k in source_cols],
                             key=f"{key}_pk_{st.session_state.config_version}")

    st.markdown("**Column Mappings** (leave blank or delete a row to ignore a column)")
    # The grid being edited; kept in session so the preview column can be refreshed without losing edits
    draft = st.session_state.get("grid_draft")
    grid = st.data_editor(
        with_rule_preview(draft if draft is not None else config_to_grid(config)), num_rows="dynamic",
        width="stretch", key=f"{key}_editor_{st.session_state.config_version}_{st.session_state.grid_version}",
        column_config={
            SOURCE_COL: st.column_config.SelectboxColumn("Source Column", options=[""] + source_cols),
            TARGET_COL: st.column_config.SelectboxColumn("Target Column", options=[""] + target_cols),
            RULE_COL: st.column_config.TextColumn(
                "Validation Rule (Optional)", default="",
                help="e.g. 'within 0.01', '+/- 5%', 'ignore case', 'same date, ignore time'"),
            PREVIEW_COL: st.column_config.TextColumn(
                PREVIEW_COL, disabled=True,
                help="How the rule will be applied. Check this before running: 'within 1' is an absolute "
                     "tolerance, 'within 1%' is a percentage of the source value."),
        },
    )
    if preview_is_stale(grid):
        # A rule was edited: redraw the grid (edits kept) so the preview matches it
        st.session_state.grid_draft = grid
        st.session_state.grid_version += 1
        st.rerun()

    with st.expander("Comparison options"):
        options = {
            "trim_strings": st.checkbox("Trim leading/trailing spaces (JD Edwards CHAR padding)", value=True,
                                        key=f"{key}_trim"),
            "blank_as_null": st.checkbox("Treat blank strings as NULL", value=True, key=f"{key}_blank"),
        }

    if not st.session_state.is_guest:
        st.download_button("💾 Save As Mapping Template (Excel)", template_bytes(grid, pk_cols),
                           file_name=f"truealign_{file_slug}_mapping_template.xlsx",
                           mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                           help="Download these mappings and primary keys to load them instantly next time",
                           key=f"{key}_tpl_dl")
    return pk_cols, grid, options


def render_mapping_workflow(pair: DataPair, key: str, run_label: str, spinner: str, results_title: str,
                            file_slug: str):
    """Step 2 (map schema) through results, identical for every tier."""
    if st.session_state.get("config_signature") != (key, pair.signature):
        # inputs changed: a mapping built for other data would be misleading
        st.session_state.config_signature = (key, pair.signature)
        st.session_state.ai_config = None
        st.session_state.pop("results", None)

    st.markdown("---")
    st.subheader("🧠 Step 2: Map Schema")
    agent = model_picker(key)
    _mapping_sources(pair, key, agent)

    if not st.session_state.ai_config:
        return

    try:
        pk_cols, grid, options = _mapping_editor(pair, key, file_slug)
    except Exception as e:
        st.error(f"Could not read columns: {pair.redact(str(e))}")
        return

    st.markdown("---")
    if st.button(run_label, type="primary", width="stretch", key=f"{key}_run"):
        if not pk_cols:
            st.error("Select at least one primary key before running the comparison.")
        else:
            with st.spinner(spinner):
                try:
                    config, notes = resolve_rules(config_from_grid(grid, pk_cols, **options), agent)
                    result = pair.run(config)
                    result.warnings[:0] = notes
                    st.session_state.results = result
                    st.toast("Comparison Complete!", icon="🎉")
                except ValueError as e:
                    st.error(pair.redact(str(e)))
                except Exception as e:
                    st.error(f"Comparison failed: {pair.redact(str(e))}")

    if st.session_state.get("results") is not None:
        render_results(st.session_state.results, key, results_title)

    st.markdown("<br>", unsafe_allow_html=True)
    if st.button("🔄 Restart Validation", width="stretch", key=f"{key}_reset"):
        reset_app()
