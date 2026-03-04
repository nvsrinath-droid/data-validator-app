import streamlit as st
import pandas as pd
import json
import base64
import os
from dotenv import load_dotenv

# App layout and styling must be set first
st.set_page_config(page_title="TrueAlign Data", page_icon="🎯", layout="wide")

# Custom CSS for a clean, professional look
st.markdown("""
    <style>
    .main { background-color: #f8f9fa; }
    h1 { color: #1e3a8a; }
    .stButton>button { width: 100%; border-radius: 5px; font-weight: bold; }
    .stDownloadButton>button { background-color: #10b981; color: white; }
    .stDownloadButton>button:hover { background-color: #059669; color: white; }
    div[data-testid="stSidebar"] { background-color: #ffffff; border-right: 1px solid #e5e7eb; }
    </style>
""", unsafe_allow_html=True)

# Important imports
from connectors.file_connector import FileConnector
from connectors.sql_connector import SQLConnector
from ai.agent import AIAgent
from core.schemas import ValidationConfig, ColumnMap
from core.comparator import DataComparator

# Load ENV logic specifically for the web app missing a .env
load_dotenv()

# Top 15 Models Dictionary mapping display name -> (litellm_model_string, required_env_var_name)
AVAILABLE_MODELS = {
    "Google Gemini 2.5 Flash": ("gemini/gemini-2.5-flash", "GEMINI_API_KEY"),
    "Google Gemini 1.5 Pro": ("gemini/gemini-1.5-pro", "GEMINI_API_KEY"),
    "OpenAI GPT-4o": ("gpt-4o", "OPENAI_API_KEY"),
    "OpenAI GPT-4o Mini": ("gpt-4o-mini", "OPENAI_API_KEY"),
    "OpenAI o1": ("o1", "OPENAI_API_KEY"),
    "OpenAI o1-mini": ("o1-mini", "OPENAI_API_KEY"),
    "Anthropic Claude 3.5 Sonnet": ("claude-3-5-sonnet-20241022", "ANTHROPIC_API_KEY"),
    "Anthropic Claude 3.5 Haiku": ("claude-3-5-haiku-20241022", "ANTHROPIC_API_KEY"),
    "Anthropic Claude 3 Opus": ("claude-3-opus-20240229", "ANTHROPIC_API_KEY"),
    "Groq LLaMA 3 70B": ("groq/llama3-70b-8192", "GROQ_API_KEY"),
    "Groq LLaMA 3 8B": ("groq/llama3-8b-8192", "GROQ_API_KEY"),
    "Groq Mixtral 8x7B": ("groq/mixtral-8x7b-32768", "GROQ_API_KEY"),
    "Cohere Command R+": ("command-r-plus", "COHERE_API_KEY"),
    "Cohere Command R": ("command-r", "COHERE_API_KEY"),
    "Mistral Large": ("mistral/mistral-large-latest", "MISTRAL_API_KEY")
}

# Initialize Session State for API Keys if they don't exist
if 'stored_keys' not in st.session_state:
    st.session_state.stored_keys = {
        "GEMINI_API_KEY": os.environ.get("GEMINI_API_KEY", ""),
        "OPENAI_API_KEY": os.environ.get("OPENAI_API_KEY", ""),
        "ANTHROPIC_API_KEY": os.environ.get("ANTHROPIC_API_KEY", ""),
        "GROQ_API_KEY": os.environ.get("GROQ_API_KEY", ""),
        "COHERE_API_KEY": os.environ.get("COHERE_API_KEY", ""),
        "MISTRAL_API_KEY": os.environ.get("MISTRAL_API_KEY", "")
    }

# Initialize Session State for user's selected models
if 'user_configured_models' not in st.session_state:
    st.session_state.user_configured_models = []

@st.dialog("⚙️ Global AI Settings & API Keys")
def settings_modal():
    st.markdown("Add the AI models you want to use and securely store their API keys.")
    
    # Model Adder
    c_add_1, c_add_2 = st.columns([3, 1])
    with c_add_1:
        # Only show models not already added
        available_to_add = [m for m in AVAILABLE_MODELS.keys() if m not in st.session_state.user_configured_models]
        model_to_add = st.selectbox("Select a model to add", available_to_add, label_visibility="collapsed")
    with c_add_2:
        if st.button("➕ Add Model", use_container_width=True, disabled=len(available_to_add)==0):
            if model_to_add:
                st.session_state.user_configured_models.append(model_to_add)
                st.rerun()
                
    st.markdown("---")
    
    # Scrollable container for the configured models
    with st.container(height=350):
        if not st.session_state.user_configured_models:
            st.info("No AI models configured yet. Please add one from the dropdown above.")
            
        for idx, model_name in enumerate(st.session_state.user_configured_models):
            litellm_model_str, required_env_key = AVAILABLE_MODELS[model_name]
            provider_name = required_env_key.split('_')[0].title()
            
            c_label, c_remove = st.columns([4, 1])
            c_label.markdown(f"**{model_name}**")
            if c_remove.button("🗑️ Remove", key=f"rm_{model_name}_{idx}"):
                st.session_state.user_configured_models.remove(model_name)
                st.rerun()
                
            # Key input
            current_val = st.session_state.stored_keys.get(required_env_key, "")
            new_val = st.text_input(
                f"{provider_name} API Key", 
                value=current_val, 
                type="password", 
                key=f"input_{required_env_key}_{idx}",
                label_visibility="collapsed",
                placeholder=f"Enter {required_env_key}"
            )
            
            if new_val != current_val:
                st.session_state.stored_keys[required_env_key] = new_val
                
            st.divider()
            
    if st.button("Save & Close", type="primary", use_container_width=True):
        st.rerun()

# State management for full app reset
if 'uploader_key' not in st.session_state:
    st.session_state.uploader_key = 0

def reset_app():
    # Clear the generated data to restart the process
    for k in ['ai_config', 'results', 'df1_full', 'df2_full']:
        if k in st.session_state:
            del st.session_state[k]
    # Increment key to clear file uploaders
    st.session_state.uploader_key += 1
    st.rerun()

# We use session state to hold the AI's configuration so it doesn't regenerate on every button click
if 'ai_config' not in st.session_state:
    st.session_state.ai_config = None

# Top level reset button
colA, colB, colC = st.columns([5, 1, 1])
with colA:
    st.title("🎯 TrueAlign Data")
    st.markdown("Easily find missing rows, map mismatched schemas, and enforce custom business rules between live databases and flat files using the power of AI.")
with colB:
    st.markdown("<br>", unsafe_allow_html=True)
    if st.button("⚙️ Settings", use_container_width=True):
        settings_modal()
with colC:
    st.markdown("<br>", unsafe_allow_html=True)
    if st.button("🔄 Reset", use_container_width=True, help="Start a new validation"):
        reset_app()

def render_sql_form(key_prefix):
    db_type = st.selectbox("Database Type", ["Snowflake", "Microsoft SQL Server", "Oracle", "PostgreSQL", "SQLite (Local)"], key=f"db_type_{key_prefix}")
    
    conn_str = ""
    if db_type == "SQLite (Local)":
        db_path = st.text_input("Database File Path", placeholder="local_production.db", key=f"sqlite_{key_prefix}")
        if db_path:
            conn_str = f"sqlite:///{db_path}"
    else:
        # Enterprise DB Form
        c1, c2 = st.columns([3, 1])
        host = c1.text_input("Host / Server Address", placeholder="e.g., my-account.snowflakecomputing.com", key=f"host_{key_prefix}")
        
        # Default ports
        default_port = {"Snowflake": "443", "Microsoft SQL Server": "1433", "Oracle": "1521", "PostgreSQL": "5432"}[db_type]
        port = c2.text_input("Port", value=default_port, key=f"port_{key_prefix}")
        
        db_name = st.text_input("Database Name", key=f"db_{key_prefix}")
        
        c3, c4 = st.columns(2)
        user = c3.text_input("Username", key=f"user_{key_prefix}")
        password = c4.text_input("Password", type="password", key=f"pass_{key_prefix}")
        
        if host and db_name and user and password:
            if db_type == "Snowflake":
                conn_str = f"snowflake://{user}:{password}@{host}/{db_name}"
            elif db_type == "Microsoft SQL Server":
                # Assuming pyodbc is installed
                conn_str = f"mssql+pyodbc://{user}:{password}@{host}:{port}/{db_name}?driver=ODBC+Driver+17+for+SQL+Server"
            elif db_type == "Oracle":
                conn_str = f"oracle+oracledb://{user}:{password}@{host}:{port}/?service_name={db_name}"
            elif db_type == "PostgreSQL":
                conn_str = f"postgresql://{user}:{password}@{host}:{port}/{db_name}"

    query = st.text_area("SQL Query", placeholder="SELECT * FROM table_name", key=f"q_{key_prefix}")
    
    if conn_str and query:
        return {"type": "sql", "conn_str": conn_str, "query": query}
    return None

# Step 1: Data Sources Selection
col1, col2 = st.columns(2)
with col1:
    st.subheader("📁 Source Data (System of Record)")
    source_type_1 = st.radio("Source 1 Type", ["File Upload", "SQL Database"], horizontal=True, key=f"src1_type_{st.session_state.uploader_key}")
    if source_type_1 == "File Upload":
        source_1 = st.file_uploader("Upload File 1", type=["csv", "xlsx"], key=f"file1_{st.session_state.uploader_key}")
    else:
        source_1 = render_sql_form(f"src1_{st.session_state.uploader_key}")

with col2:
    st.subheader("📄 External Data (To Compare)")
    source_type_2 = st.radio("Source 2 Type", ["File Upload", "SQL Database"], horizontal=True, key=f"src2_type_{st.session_state.uploader_key}")
    if source_type_2 == "File Upload":
        source_2 = st.file_uploader("Upload File 2", type=["csv", "xlsx"], key=f"file2_{st.session_state.uploader_key}")
    else:
        source_2 = render_sql_form(f"src2_{st.session_state.uploader_key}")

if source_1 and source_2:
    st.markdown("---")
    st.subheader("🧠 Step 2: Select AI Model & Map Schema")
    
    if not st.session_state.user_configured_models:
        st.warning("⚠️ No AI Models configured. Please click the ⚙️ Settings menu (top right) to add a model and API key.")
        st.stop()
        
    # Pull model selection out of the sidebar and into the main flow
    c_model, _ = st.columns([1, 2])
    with c_model:
        selected_model_display = st.selectbox("Active AI Model", st.session_state.user_configured_models)
        litellm_model_str, required_env_key = AVAILABLE_MODELS[selected_model_display]
        active_api_key = st.session_state.stored_keys.get(required_env_key, "")

    if not active_api_key:
         st.warning(f"⚠️ You must configure your `{required_env_key}` in the ⚙️ Settings menu (top right) to use {selected_model_display}.")
         st.stop()
         
    # Init connectors dynamically based on the user's choice
    def init_connector(source_data):
        if isinstance(source_data, dict) and source_data.get('type') == 'sql':
            return SQLConnector(source_data['conn_str'], source_data['query'])
        else:
            return FileConnector(source_data)
            
    try:
        conn1 = init_connector(source_1)
        conn2 = init_connector(source_2)
    except Exception as e:
        st.error(f"Error connecting to data source: {str(e)}")
        st.stop()
    
    # UI for choosing between AI Generation or Loading a Template
    c_generate, c_upload = st.columns(2)
    
    with c_generate:
        # Generate Config Button
        if st.button(f"✨ Auto-Map with {selected_model_display}", type="primary", use_container_width=True):
            with st.spinner(f'{selected_model_display} is reading your structured data and building a mapping schema...'):
                try:
                    sample1 = conn1.get_sample_data(5).to_csv(index=False)
                    sample2 = conn2.get_sample_data(5).to_csv(index=False)
                    
                    agent = AIAgent(model_name=litellm_model_str, api_key=active_api_key)
                    st.session_state.ai_config = agent.suggest_configuration(sample1, sample2)
                    st.success("AI Analysis Complete!")
                except Exception as e:
                    st.error(f"Error during AI analysis: {str(e)}")
                    
    with c_upload:
        template_file = st.file_uploader("📥 Or load a Saved Template (CSV)", type=["csv"], key=f"tpl_{st.session_state.uploader_key}", label_visibility="collapsed")
        if template_file:
            try:
                tpl_df = pd.read_csv(template_file)
                # Ensure the CSV has the expected columns
                if all(c in tpl_df.columns for c in ["File 1 Column", "File 2 Column", "Validation Rule (Optional)"]):
                    new_mappings = []
                    for _, row in tpl_df.iterrows():
                        c1 = str(row["File 1 Column"]) if pd.notna(row["File 1 Column"]) else ""
                        c2 = str(row["File 2 Column"]) if pd.notna(row["File 2 Column"]) else ""
                        rule = str(row["Validation Rule (Optional)"]) if pd.notna(row["Validation Rule (Optional)"]) else ""
                        if rule.lower() == 'nan': rule = ""
                        
                        if c1 and c2:
                            new_mappings.append(ColumnMap(file1_column=c1, file2_column=c2, validation_rule=rule if rule else None))
                    
                    # Store it directly into session state bypassing the AI
                    st.session_state.ai_config = ValidationConfig(
                        primary_keys=[], # Primary keys will be manually selected by user next
                        column_mappings=new_mappings,
                        ignore_columns=[]
                    )
                    st.success("Template Loaded Successfully!")
                else:
                    st.error("Invalid template format. Must contain 'File 1 Column', 'File 2 Column', and 'Validation Rule (Optional)'.")
            except Exception as e:
                st.error(f"Failed to load template: {str(e)}")
                
    # If we have a configuration (either just generated, or from previous click)
    if st.session_state.ai_config:
        config = st.session_state.ai_config
        
        # UI for editing mappings
        st.write("Review and adjust the AI's suggestions before running the final comparison:")
        
        # Primary Keys UI
        st.markdown("**Primary Keys** (The unique identifier to link rows together)")
        pk_cols = st.multiselect("Select Primary Keys (File 1 Columns)", 
                                 options=conn1.get_sample_data(1).columns.tolist(),
                                 default=config.primary_keys)
        
        # Column Mappings UI as an editable dataframe with DROPDOWNS
        st.markdown("**Column Mappings** (Leave blank or delete a row to ignore a column)")
        
        # Get the actual column names from the uploaded files, plus a blank option
        file1_cols = [""] + conn1.get_sample_data(1).columns.tolist()
        file2_cols = [""] + conn2.get_sample_data(1).columns.tolist()
        
        mapping_data = [{"File 1 Column": m.file1_column, "File 2 Column": m.file2_column, "Validation Rule (Optional)": m.validation_rule or ""} for m in config.column_mappings]
        mapping_df = pd.DataFrame(mapping_data)

        # Configure the dataframe to use dropdowns
        edited_mapping_df = st.data_editor(
            mapping_df, 
            num_rows="dynamic", 
            use_container_width=True,
            column_config={
                "File 1 Column": st.column_config.SelectboxColumn(
                    "Source Column (File 1)",
                    options=file1_cols,
                    required=False
                ),
                "File 2 Column": st.column_config.SelectboxColumn(
                    "Target Column (File 2)",
                    options=file2_cols,
                    required=False
                ),
                "Validation Rule (Optional)": st.column_config.TextColumn(
                    "Validation Rule (Optional)",
                    help="e.g., 'Must be within $5' or 'Ignore case'",
                    default=""
                )
            }
        )
        )
        
        # Export Template Button
        st.download_button(
            label="💾 Save As Mapping Template (CSV)",
            data=edited_mapping_df.to_csv(index=False).encode('utf-8'),
            file_name="truealign_mapping_template.csv",
            mime="text/csv",
            help="Download these mappings and rules to instantly load them next time"
        )
        
        st.markdown("---")
        # --- Step 3: Run Comparison ---
        if st.button("🚀 Run Full Data Comparison", type="primary", use_container_width=True):
            with st.spinner('Comparing all rows...'):
                # Rebuild config object from the UI edited state, safely dropping empty/deleted rows
                new_mappings = []
                rules_dict = {}
                for index, row in edited_mapping_df.iterrows():
                    c1_raw = row.get('File 1 Column')
                    c2_raw = row.get('File 2 Column')
                    rule_raw = row.get('Validation Rule (Optional)')
                    
                    c1 = str(c1_raw).strip() if pd.notna(c1_raw) and c1_raw is not None else ""
                    c2 = str(c2_raw).strip() if pd.notna(c2_raw) and c2_raw is not None else ""
                    rule = str(rule_raw).strip() if pd.notna(rule_raw) and rule_raw is not None else ""
                    
                    if rule.lower() == 'nan': rule = ""
                    
                    # Only map if both columns are provided and not NaN
                    if c1 and c2 and c1.lower() != 'nan' and c2.lower() != 'nan' and c1 != 'None' and c2 != 'None':
                        new_mappings.append(ColumnMap(file1_column=c1, file2_column=c2, validation_rule=rule if rule else None))
                        if rule:
                            rules_dict[c1] = rule
                
                final_config = ValidationConfig(
                    primary_keys=pk_cols,
                    column_mappings=new_mappings,
                    ignore_columns=[]
                )
                
                # Execute AI Logic if rules exist
                rule_code = None
                if rules_dict:
                    st.toast(f"Generating custom validation rules with {selected_model_display}...", icon='🧠')
                    agent = AIAgent(model_name=litellm_model_str, api_key=active_api_key)
                    rule_code = agent.generate_rule_evaluator_code(rules_dict)
                
                # Execute Core Logic
                comparator = DataComparator(final_config, rule_code=rule_code)
                st.session_state.df1_full = conn1.read_data()
                st.session_state.df2_full = conn2.read_data()
                st.session_state.results = comparator.compare(st.session_state.df1_full, st.session_state.df2_full)
                
                st.toast('Comparison Complete!', icon='🎉')
                
        # --- Step 4: Display Results & Downloads ---
        if st.session_state.get('results'):
            results = st.session_state.results
            df1_full = st.session_state.df1_full
            df2_full = st.session_state.df2_full
            
            st.subheader("📊 Validation Results")
            
            # Feature: High Level Metric Summary
            st.markdown("### Record Counts & Summary")
            m1, m2, m3 = st.columns(3)
            m1.metric("File 1 Total Rows", f"{len(df1_full):,}")
            m2.metric("File 2 Total Rows", f"{len(df2_full):,}")
            
            # Optional: Grand Totals for matching numeric columns
            total_diff = len(df1_full) - len(df2_full)
            m3.metric("Row Count Difference", f"{total_diff:,}", delta=total_diff, delta_color="inverse")
            
            st.markdown("---")
            
            st.markdown("### Detailed Exceptions")
            
            def get_flattened_mismatches_df(mismatches_list):
                flat_data = []
                for item in mismatches_list:
                    pk_str = str(item["primary_keys"])
                    for diff in item["differences"]:
                        flat_data.append({
                            "Primary Key": pk_str,
                            "Column": diff["column"],
                            "File 1 Value": diff["file1_value"],
                            "File 2 Value": diff["file2_value"],
                            "Validation Rule": diff.get("validation_rule", ""),
                            "Remarks": diff.get("error", "Exact match failed")
                        })
                return pd.DataFrame(flat_data)

            # We need a helper to generate CSV strings for download
            def to_csv_download(data_dict_list, is_mismatch=False):
                if not data_dict_list: return None
                
                if is_mismatch:
                     return get_flattened_mismatches_df(data_dict_list).to_csv(index=False).encode('utf-8')
                else:
                     return pd.DataFrame(data_dict_list).to_csv(index=False).encode('utf-8')

            # Create tabs for clean viewing
            tab1, tab2, tab3 = st.tabs(["Mismatched Values", "Missing in Source", "Missing in External"])
            
            with tab1:
                mismatches = results.get('mismatches', [])
                st.metric("Total Mismatched Rows", len(mismatches))
                if mismatches:
                    flat_df = get_flattened_mismatches_df(mismatches)
                    csv_data = flat_df.to_csv(index=False).encode('utf-8')
                    st.download_button("Download Mismatches CSV", data=csv_data, file_name="mismatches.csv", mime="text/csv")
                    st.dataframe(flat_df.astype(str)) # Easy viewer
            
            with tab2:
                 missing_f1 = results.get('missing_in_file1', [])
                 st.metric("Total Rows Missing in Source File", len(missing_f1))
                 if missing_f1:
                     csv_data = to_csv_download(missing_f1)
                     st.download_button("Download Missing (Source) CSV", data=csv_data, file_name="missing_source.csv", mime="text/csv")
                     st.dataframe(pd.DataFrame(missing_f1))
                     
            with tab3:
                 missing_f2 = results.get('missing_in_file2', [])
                 st.metric("Total Rows Missing in External File", len(missing_f2))
                 if missing_f2:
                     csv_data = to_csv_download(missing_f2)
                     st.download_button("Download Missing (External) CSV", data=csv_data, file_name="missing_external.csv", mime="text/csv")
                     st.dataframe(pd.DataFrame(missing_f2))
            
            st.markdown("---")
            if st.button("🔄 Start New Data Validation", type="secondary", use_container_width=True):
                reset_app()
