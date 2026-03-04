import streamlit as st
import pandas as pd
import json
import base64
import os
from dotenv import load_dotenv

# App layout and styling must be set first
st.set_page_config(page_title="TrueAlign Data", page_icon="🎯", layout="wide")

def inject_premium_css():
    st.markdown("""
    <style>
    /* Google Fonts */
    @import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&display=swap');

    /* Global Typography & Colors */
    html, body, [class*="css"], .stApp {
        font-family: 'Inter', sans-serif !important;
        background: linear-gradient(135deg, #0f172a 0%, #172554 100%) !important;
        background-attachment: fixed !important;
        color: #f8fafc !important;
    }
    
    .stApp > header {
        background-color: transparent !important;
    }

    /* Hide Streamlit Clutter */
    #MainMenu {visibility: hidden;}
    footer {visibility: hidden;}
    header {visibility: hidden;}

    /* Headers */
    h1, h2, h3, h4, h5, h6 {
        color: #ffffff !important;
        font-weight: 600 !important;
        letter-spacing: -0.02em !important;
    }
    
    p, span, div {
        color: #f8fafc;
    }

    /* Primary Container Mod */
    .main .block-container {
        padding-top: 2rem !important;
        max-width: 1200px;
    }

    /* Splash Page Buttons as Glass Cards */
    div[data-testid="column"] button[kind="secondary"] {
        background: rgba(255, 255, 255, 0.05) !important;
        border: 1px solid rgba(255, 255, 255, 0.1) !important;
        backdrop-filter: blur(12px) !important;
        -webkit-backdrop-filter: blur(12px) !important;
        border-radius: 16px !important;
        height: 60px !important;
        color: #ffffff !important;
        transition: all 0.3s cubic-bezier(0.4, 0, 0.2, 1) !important;
        box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.1), 0 24px 38px 3px rgba(0, 0, 0, 0.14) !important;
    }
    
    div[data-testid="column"] button[kind="secondary"] p {
        color: #ffffff !important;
        font-weight: 600 !important;
        font-size: 1.05rem !important;
    }
    
    div[data-testid="column"] button[kind="secondary"]:hover {
        background: rgba(255, 255, 255, 0.1) !important;
        border-color: rgba(255, 255, 255, 0.3) !important;
        transform: translateY(-2px) !important;
        box-shadow: 0 10px 15px -3px rgba(0, 0, 0, 0.2), 0 24px 38px 3px rgba(0, 0, 0, 0.2) !important;
    }
    
    /* Primary Call to Action Buttons */
    button[kind="primary"] {
        background: linear-gradient(135deg, #3b82f6 0%, #2563eb 100%) !important;
        border: none !important;
        border-radius: 12px !important;
        color: white !important;
        font-weight: 600 !important;
        box-shadow: 0 4px 14px 0 rgba(37, 99, 235, 0.39) !important;
    }
    button[kind="primary"] p {
        color: white !important;
        font-weight: 600 !important;
    }
    
    button[kind="primary"]:hover {
        background: linear-gradient(135deg, #60a5fa 0%, #3b82f6 100%) !important;
        box-shadow: 0 6px 20px rgba(37, 99, 235, 0.5) !important;
        transform: translateY(-1px) !important;
    }

    /* Inputs, Textareas, Selectboxes */
    .stTextInput>div>div>input, .stSelectbox>div>div>div, .stTextArea>div>div>textarea {
        background-color: rgba(15, 23, 42, 0.6) !important;
        border: 1px solid rgba(255, 255, 255, 0.1) !important;
        border-radius: 12px !important;
        color: white !important;
        transition: border-color 0.2s ease;
    }
    
    .stTextInput>div>div>input:focus, .stSelectbox>div>div>div:focus, .stTextArea>div>div>textarea:focus {
        border-color: #3b82f6 !important;
        box-shadow: 0 0 0 1px #3b82f6 !important;
    }

    /* Text inside Inputs */
    .stTextInput>div>div>input::placeholder, .stTextArea>div>div>textarea::placeholder {
        color: #94a3b8 !important;
    }
    
    /* Dataframe container */
    [data-testid="stDataFrame"] {
        border-radius: 16px;
        overflow: hidden;
        border: 1px solid rgba(255, 255, 255, 0.1);
        box-shadow: 0 10px 15px -3px rgba(0, 0, 0, 0.1);
    }
    
    /* Tabs */
    .stTabs [data-baseweb="tab-list"] {
        gap: 8px;
        background-color: rgba(255, 255, 255, 0.03);
        padding: 8px;
        border-radius: 16px;
        border: 1px solid rgba(255, 255, 255, 0.05);
    }
    .stTabs [data-baseweb="tab"] {
        background-color: transparent;
        border-radius: 10px;
        color: #94a3b8 !important;
        border: none !important;
    }
    .stTabs [aria-selected="true"] {
        background-color: rgba(255, 255, 255, 0.1) !important;
        color: white !important;
    }

    /* Info/Warning/Error boxes */
    .stAlert {
        background-color: rgba(15, 23, 42, 0.5) !important;
        backdrop-filter: blur(16px) !important;
        -webkit-backdrop-filter: blur(16px) !important;
        border-radius: 16px !important;
        border: 1px solid rgba(255, 255, 255, 0.08) !important;
        color: #f8fafc !important;
        box-shadow: 0 10px 25px -5px rgba(0, 0, 0, 0.3) !important;
    }
    
    /* Streamlit Dialog Modal */
    div[role="dialog"] {
        background: linear-gradient(135deg, #1e293b 0%, #0f172a 100%) !important;
        border: 1px solid rgba(255,255,255,0.1);
        border-radius: 24px;
        box-shadow: 0 25px 50px -12px rgba(0, 0, 0, 0.5);
    }
    
    /* File Uploader styling */
    [data-testid="stFileUploadDropzone"] {
        background-color: rgba(255, 255, 255, 0.02) !important;
        border: 2px dashed rgba(255, 255, 255, 0.1) !important;
        border-radius: 16px !important;
        transition: all 0.3s ease;
    }
    [data-testid="stFileUploadDropzone"]:hover {
        background-color: rgba(255, 255, 255, 0.05) !important;
        border-color: #3b82f6 !important;
    }
    
    /* Labels */
    label, label p, label div {
        color: #cbd5e1 !important;
        font-weight: 500 !important;
    }

    </style>
    """, unsafe_allow_html=True)

# Inject the premium Apple-style aesthetics
inject_premium_css()

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
    for k in ['ai_config', 'results', 'df1_full', 'df2_full', 'execution_tier']:
        if k in st.session_state:
            del st.session_state[k]
    # Increment key to clear file uploaders
    st.session_state.uploader_key += 1
    # Clear URL params
    st.query_params.clear()
    st.rerun()

# We use session state to hold the AI's configuration so it doesn't regenerate on every button click
if 'ai_config' not in st.session_state:
    st.session_state.ai_config = None

# Top level reset button
colA, colB, colC = st.columns([5, 1, 1])
with colA:
    st.markdown("<a href='/' target='_self' style='text-decoration: none;'><h1 style='display:inline; margin: 0; padding: 0;'>🎯 TrueAlign Data</h1></a>", unsafe_allow_html=True)
    st.markdown("<br>Easily find missing rows, map mismatched schemas, and enforce custom business rules between live databases and flat files using the power of AI.", unsafe_allow_html=True)
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

# --- SPLASH PAGE ROUTER WITH BROWSER TAB SYNC ---
# Grab the URL query parameters to support Browser Back/Forward buttons
query_params = st.query_params

# If the URL contains an explicit engine, ensure session state matches
if "engine" in query_params:
    st.session_state.execution_tier = query_params["engine"]
# If the URL is empty but session state has an engine (e.g., from a direct button click), sync the URL
elif st.session_state.get('execution_tier'):
    st.query_params["engine"] = st.session_state.execution_tier

if st.session_state.get('execution_tier') is None:
    # Clear URL params if on splash page
    st.query_params.clear()
    
    st.markdown("---")
    st.subheader("Select a Data Validation Engine")
    st.markdown("Choose the processing tier that deeply matches your data volume and source.")
    
    c1, c2, c3 = st.columns(3)
    with c1:
        st.info("**🚀 Daily Ad-Hoc Checkups**\n\nPerfect for standard daily tasks.\n\n- Fast In-Memory Processing\n- Upload Excel & CSV files up to ~200MB\n- Run DB Queries up to ~500k rows")
        if st.button("Launch Ad-Hoc Engine", type="primary", use_container_width=True):
            st.session_state.execution_tier = "standard"
            st.query_params["engine"] = "standard"
            st.rerun()
            
    with c2:
        st.warning("**🏢 Massive Log Files**\n\nFor massive flat-file datasets.\n\n- Advanced Disk Streaming Engine\n- Avoids memory bottlenecks completely\n- Parses local Gigabyte flat files")
        if st.button("Launch Massive File Engine", type="primary", use_container_width=True):
            st.session_state.execution_tier = "heavy"
            st.query_params["engine"] = "heavy"
            st.rerun()
            
    with c3:
        st.error("**🌐 Enterprise SQL Warehouses**\n\nFor enterprise SQL data warehouses.\n\n- Zero data downloading required\n- Translates AI rules natively\n- Infinite database scale")
        if st.button("Launch Enterprise SQL Engine", type="primary", use_container_width=True):
            st.session_state.execution_tier = "pushdown"
            st.query_params["engine"] = "pushdown"
            st.rerun()
            
    st.stop()


if st.session_state.execution_tier == "standard":
    st.markdown(f"**🟢 Active Engine:** Daily Ad-Hoc Checkups")
    
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
            
        st.markdown("<br>", unsafe_allow_html=True)
        if st.button("🔄 Start New Validation (Bottom)", use_container_width=True):
            reset_app()

elif st.session_state.execution_tier == "heavy":
    st.markdown(f"**🟢 Active Engine:** Massive Log Files")
    
    # Step 1: Data Sources Selection (Files Only for Heavy Engine)
    col1, col2 = st.columns(2)
    with col1:
        st.subheader("📁 Source Data (System of Record)")
        source_1 = st.file_uploader("Upload MASSIVE File 1", type=["csv"], key=f"hfile1_{st.session_state.uploader_key}")

    with col2:
        st.subheader("📄 External Data (To Compare)")
        source_2 = st.file_uploader("Upload MASSIVE File 2", type=["csv"], key=f"hfile2_{st.session_state.uploader_key}")

    if source_1 and source_2:
        st.markdown("---")
        st.subheader("🧠 Step 2: Select AI Model & Map Schema")
        
        if not st.session_state.user_configured_models:
            st.warning("⚠️ No AI Models configured. Please click the ⚙️ Settings menu (top right) to add a model and API key.")
            st.stop()
            
        c_model, _ = st.columns([1, 2])
        with c_model:
            selected_model_display = st.selectbox("Active AI Model", st.session_state.user_configured_models, key="heavy_model")
            litellm_model_str, required_env_key = AVAILABLE_MODELS[selected_model_display]
            active_api_key = st.session_state.stored_keys.get(required_env_key, "")

        if not active_api_key:
             st.warning(f"⚠️ You must configure your `{required_env_key}` in the ⚙️ Settings menu (top right) to use {selected_model_display}.")
             st.stop()
             
        # Save large files to disk temporarily so DuckDB can read them without RAM overload
        import tempfile
        import os
        
        t1 = tempfile.NamedTemporaryFile(delete=False, suffix=".csv")
        t1.write(source_1.getvalue())
        t1.close()
        
        t2 = tempfile.NamedTemporaryFile(delete=False, suffix=".csv")
        t2.write(source_2.getvalue())
        t2.close()
        
        # UI for choosing AI Mapping Generation vs Uploading a Heavy Template
        c_generate, c_upload = st.columns(2)
        
        with c_generate:
            if st.button(f"✨ Auto-Map Header Rows with {selected_model_display}", type="primary", use_container_width=True, key="h_analyze"):
                with st.spinner(f'Extracting headers and building a mapping schema...'):
                    try:
                        # DuckDB can sniff headers insanely fast from massive files
                        import duckdb
                        s1_header = duckdb.query(f"SELECT * FROM read_csv_auto('{t1.name}') LIMIT 5").df()
                        s2_header = duckdb.query(f"SELECT * FROM read_csv_auto('{t2.name}') LIMIT 5").df()
                        
                        agent = AIAgent(model_name=litellm_model_str, api_key=active_api_key)
                        st.session_state.ai_config = agent.suggest_configuration(s1_header.to_csv(index=False), s2_header.to_csv(index=False))
                        st.session_state.heavy_files = (t1.name, t2.name)
                        st.success("AI Schema Analysis Complete!")
                    except Exception as e:
                        st.error(f"Error during AI analysis: {str(e)}")
                        
        with c_upload:
            template_file = st.file_uploader("📥 Or load a Saved Template (CSV)", type=["csv"], key=f"htpl_{st.session_state.uploader_key}", label_visibility="collapsed")
            if template_file:
                try:
                    tpl_df = pd.read_csv(template_file)
                    if all(c in tpl_df.columns for c in ["File 1 Column", "File 2 Column", "Validation Rule (Optional)"]):
                        new_mappings = []
                        for _, row in tpl_df.iterrows():
                            c1 = str(row["File 1 Column"]) if pd.notna(row["File 1 Column"]) else ""
                            c2 = str(row["File 2 Column"]) if pd.notna(row["File 2 Column"]) else ""
                            rule = str(row["Validation Rule (Optional)"]) if pd.notna(row["Validation Rule (Optional)"]) else ""
                            if rule.lower() == 'nan': rule = ""
                            if c1 and c2:
                                new_mappings.append(ColumnMap(file1_column=c1, file2_column=c2, validation_rule=rule if rule else None))
                        
                        st.session_state.ai_config = ValidationConfig(primary_keys=[], column_mappings=new_mappings, ignore_columns=[])
                        st.session_state.heavy_files = (t1.name, t2.name)
                        st.success("Template Loaded Successfully!")
                    else:
                        st.error("Invalid template format.")
                except Exception as e:
                    st.error(f"Failed to load template: {str(e)}")

        # --- HEAVY GRID CONFIGURATOR ---
        if st.session_state.ai_config and st.session_state.get('heavy_files'):
            config = st.session_state.ai_config
            f1_path, f2_path = st.session_state.heavy_files
            
            # Re-read headers for the dropdown options
            import duckdb
            f1_cols = [""] + duckdb.query(f"SELECT * FROM read_csv_auto('{f1_path}') LIMIT 1").df().columns.tolist()
            f2_cols = [""] + duckdb.query(f"SELECT * FROM read_csv_auto('{f2_path}') LIMIT 1").df().columns.tolist()
            
            st.write("Review and adjust the AI's suggestions before running the final Heavy comparison:")
            
            st.markdown("**Primary Keys**")
            pk_cols = st.multiselect("Select Primary Keys (File 1 Columns)", options=[x for x in f1_cols if x], default=config.primary_keys, key="h_pk")
            
            st.markdown("**Column Mappings**")
            mapping_data = [{"File 1 Column": m.file1_column, "File 2 Column": m.file2_column, "Validation Rule (Optional)": m.validation_rule or ""} for m in config.column_mappings]
            mapping_df = pd.DataFrame(mapping_data)

            edited_mapping_df = st.data_editor(
                mapping_df, num_rows="dynamic", use_container_width=True, key="h_editor",
                column_config={
                    "File 1 Column": st.column_config.SelectboxColumn("Source Column", options=f1_cols),
                    "File 2 Column": st.column_config.SelectboxColumn("Target Column", options=f2_cols),
                    "Validation Rule (Optional)": st.column_config.TextColumn("Validation Rule")
                }
            )
            
            # Export Template
            st.download_button(
                label="💾 Save As Mapping Template (CSV)",
                data=edited_mapping_df.to_csv(index=False).encode('utf-8'),
                file_name="truealign_heavy_mapping_template.csv",
                mime="text/csv",
                key="h_download_tpl",
                help="Download these mappings and rules to instantly load them next time"
            )
            
            st.markdown("---")
            if st.button("🚀 Run Heavy File Comparison (Disk Streaming)", type="primary", use_container_width=True, key="h_run"):
                with st.spinner('Piping massive files to DuckDB analytic engine...'):
                    new_mappings = []
                    rules_dict = {}
                    for index, row in edited_mapping_df.iterrows():
                        c1, c2, rule = str(row.get('File 1 Column')), str(row.get('File 2 Column')), str(row.get('Validation Rule (Optional)'))
                        if c1 and c2 and c1 != 'None' and c2 != 'None' and c1 != 'nan':
                            new_mappings.append(ColumnMap(file1_column=c1, file2_column=c2, validation_rule=rule if rule != 'nan' else None))
                            if rule and rule != 'nan':
                                rules_dict[c1] = rule
                    
                    final_config = ValidationConfig(primary_keys=pk_cols, column_mappings=new_mappings)
                    
                    from core.engines.duckdb_engine import DuckDBEngine
                    heavy_engine = DuckDBEngine(final_config, rules_dict=rules_dict)
                    
                    try:
                        st.session_state.results = heavy_engine.compare(f1_path, f2_path)
                        st.toast('Massive Comparison Complete!', icon='🐘')
                        
                        # Clean up temp files
                        os.unlink(f1_path)
                        os.unlink(f2_path)
                        st.session_state.heavy_files = None
                    except Exception as e:
                        st.error(f"DuckDB Query Failed: {str(e)}")
                        
            # Results UI
            if 'results' in st.session_state:
                res = st.session_state.results
                total1, total2 = res.get('Total Rows File 1', 0), res.get('Total Rows File 2', 0)
                mismatches = len(res.get('Data Mismatches', []))
                
                st.subheader("📊 Heavy Validation Results")
                k1, k2, k3, k4, k5 = st.columns(5)
                k1.metric("Total Rows (File 1)", f"{total1:,}")
                k2.metric("Total Rows (File 2)", f"{total2:,}")
                k3.metric("Exact Matches", f"{len(res.get('Exact Matches', [])):,}")
                k4.metric("Missing Rows", f"{(len(res.get('Missing in File 1 (Found in 2)', [])) + len(res.get('Missing in File 2 (Found in 1)', []))):,}")
                k5.metric("Data Mismatches", f"{mismatches:,}")
                
                t1, t2, t3, t4 = st.tabs(["📝 Mismatch Report", "❌ Missing in 1", "❌ Missing in 2", "✅ Exact Matches"])
                with t1:
                    if mismatches > 0: st.dataframe(pd.DataFrame(res.get('Mismatch Breakdown', [])), use_container_width=True)
                    else: st.success("No heavy mismatches found!")
                with t2: st.dataframe(res.get('Missing in File 1 (Found in 2)', pd.DataFrame()), use_container_width=True)
                with t3: st.dataframe(res.get('Missing in File 2 (Found in 1)', pd.DataFrame()), use_container_width=True)
                with t4: st.dataframe(res.get('Exact Matches', pd.DataFrame()), use_container_width=True)
                
                st.markdown("<br>", unsafe_allow_html=True)
                if st.button("🔄 Start New Validation (Bottom)", use_container_width=True, key="h_reset"):
                    reset_app()

elif st.session_state.execution_tier == "pushdown":
    st.markdown(f"**🟢 Active Engine:** Enterprise SQL Warehouses")
    
    st.subheader("🏢 Enterprise Database Connection")
    st.markdown("Enter your database credentials to execute validation natively.")
    
    # We use a single connection for the Pushdown engine so records can be joined natively
    db_type_pd = st.selectbox("SQL Dialect", ["Snowflake", "Microsoft SQL Server", "Oracle", "PostgreSQL", "SQLite (Local)"], key="pd_db_type")
    
    conn_str_pd = ""
    if db_type_pd == "SQLite (Local)":
        db_path = st.text_input("Database File Path", placeholder="local_production.db", key="pd_sqlite")
        if db_path: conn_str_pd = f"sqlite:///{db_path}"
    else:
        c1, c2 = st.columns([3, 1])
        host = c1.text_input("Server Host", key="pd_host")
        port = c2.text_input("Port", value={"Snowflake": "443", "Microsoft SQL Server": "1433", "Oracle": "1521", "PostgreSQL": "5432"}[db_type_pd], key="pd_port")
        db_name = st.text_input("Database Name", key="pd_db")
        c3, c4 = st.columns(2)
        user = c3.text_input("Username", key="pd_user")
        password = c4.text_input("Password", type="password", key="pd_pass")
        
        if host and db_name and user and password:
            if db_type_pd == "Snowflake": conn_str_pd = f"snowflake://{user}:{password}@{host}/{db_name}"
            elif db_type_pd == "Microsoft SQL Server": conn_str_pd = f"mssql+pyodbc://{user}:{password}@{host}:{port}/{db_name}?driver=ODBC+Driver+17+for+SQL+Server"
            elif db_type_pd == "Oracle": conn_str_pd = f"oracle+oracledb://{user}:{password}@{host}:{port}/?service_name={db_name}"
            elif db_type_pd == "PostgreSQL": conn_str_pd = f"postgresql://{user}:{password}@{host}:{port}/{db_name}"

    st.markdown("---")
    c_q1, c_q2 = st.columns(2)
    with c_q1:
        st.subheader("📁 System of Record")
        q1 = st.text_area("SQL Query 1", placeholder="SELECT * FROM main_finance_table", key="pd_q1")
    with c_q2:
        st.subheader("📄 External Data")
        q2 = st.text_area("SQL Query 2", placeholder="SELECT * FROM external_vendor_table", key="pd_q2")

    if conn_str_pd and q1 and q2:
        st.markdown("---")
        st.subheader("🧠 Step 2: Select AI Model & Map Schema")
        
        if not st.session_state.user_configured_models:
            st.warning("⚠️ No AI Models configured. Please click the ⚙️ Settings menu (top right) to add a model and API key.")
            st.stop()
            
        c_model, _ = st.columns([1, 2])
        with c_model:
            selected_model_display = st.selectbox("Active AI Model", st.session_state.user_configured_models, key="pd_model")
            litellm_model_str, required_env_key = AVAILABLE_MODELS[selected_model_display]
            active_api_key = st.session_state.stored_keys.get(required_env_key, "")

        if not active_api_key:
             st.warning(f"⚠️ You must configure your `{required_env_key}` in the ⚙️ Settings menu (top right) to use {selected_model_display}.")
             st.stop()
             
        # UI for choosing AI Mapping Generation vs Uploading a Template
        c_generate, c_upload = st.columns(2)
        
        with c_generate:
            if st.button(f"✨ Auto-Map Queries with {selected_model_display}", type="primary", use_container_width=True, key="pd_analyze"):
                with st.spinner(f'Extracting headers from the database and building a mapping schema...'):
                    try:
                        from sqlalchemy import create_engine, text
                        tmp_engine = create_engine(conn_str_pd)
                        with tmp_engine.connect() as conn:
                            s1_sample = pd.read_sql(text(q1 + " LIMIT 5" if "LIMIT" not in q1.upper() else q1), conn)
                            s2_sample = pd.read_sql(text(q2 + " LIMIT 5" if "LIMIT" not in q2.upper() else q2), conn)
                            
                        agent = AIAgent(model_name=litellm_model_str, api_key=active_api_key)
                        st.session_state.ai_config = agent.suggest_configuration(s1_sample.to_csv(index=False), s2_sample.to_csv(index=False))
                        st.session_state.pd_data = (conn_str_pd, q1, q2)
                        st.success("AI Schema Analysis Complete!")
                    except Exception as e:
                        st.error(f"Database Query Failed: {str(e)}")
                        
        with c_upload:
            template_file = st.file_uploader("📥 Or load a Saved Template (CSV)", type=["csv"], key=f"pdtpl_{st.session_state.uploader_key}", label_visibility="collapsed")
            if template_file:
                try:
                    tpl_df = pd.read_csv(template_file)
                    if all(c in tpl_df.columns for c in ["File 1 Column", "File 2 Column", "Validation Rule (Optional)"]):
                        new_mappings = []
                        for _, row in tpl_df.iterrows():
                            c1 = str(row["File 1 Column"]) if pd.notna(row["File 1 Column"]) else ""
                            c2 = str(row["File 2 Column"]) if pd.notna(row["File 2 Column"]) else ""
                            rule = str(row["Validation Rule (Optional)"]) if pd.notna(row["Validation Rule (Optional)"]) else ""
                            if rule.lower() == 'nan': rule = ""
                            if c1 and c2:
                                new_mappings.append(ColumnMap(file1_column=c1, file2_column=c2, validation_rule=rule if rule else None))
                        
                        st.session_state.ai_config = ValidationConfig(primary_keys=[], column_mappings=new_mappings, ignore_columns=[])
                        st.session_state.pd_data = (conn_str_pd, q1, q2)
                        st.success("Template Loaded Successfully!")
                except Exception as e:
                    st.error(f"Failed to load template: {str(e)}")

        # --- PUSHDOWN GRID CONFIGURATOR ---
        if st.session_state.ai_config and st.session_state.get('pd_data'):
            config = st.session_state.ai_config
            _, pd_q1, pd_q2 = st.session_state.pd_data
            
            # Re-fetch headers to populate mapping dropdowns
            try:
                from sqlalchemy import create_engine, text
                tmp_engine = create_engine(conn_str_pd)
                with tmp_engine.connect() as conn:
                    header1 = pd.read_sql(text(pd_q1 + " LIMIT 1" if "LIMIT" not in pd_q1.upper() else pd_q1), conn).columns.tolist()
                    header2 = pd.read_sql(text(pd_q2 + " LIMIT 1" if "LIMIT" not in pd_q2.upper() else pd_q2), conn).columns.tolist()
            except Exception:
                header1, header2 = [], []
                
            f1_cols = [""] + header1
            f2_cols = [""] + header2
            
            st.write("Review your AI mapping before pushing the execution engine into the remote database:")
            
            st.markdown("**Primary Keys**")
            pk_cols = st.multiselect("Select Primary Keys (Query 1 Columns)", options=[x for x in f1_cols if x], default=config.primary_keys, key="pd_pk")
            
            st.markdown("**Column Mappings**")
            mapping_data = [{"File 1 Column": m.file1_column, "File 2 Column": m.file2_column, "Validation Rule (Optional)": m.validation_rule or ""} for m in config.column_mappings]
            mapping_df = pd.DataFrame(mapping_data)

            edited_mapping_df = st.data_editor(
                mapping_df, num_rows="dynamic", use_container_width=True, key="pd_editor",
                column_config={
                    "File 1 Column": st.column_config.SelectboxColumn("Source Column", options=f1_cols),
                    "File 2 Column": st.column_config.SelectboxColumn("Target Column", options=f2_cols),
                    "Validation Rule (Optional)": st.column_config.TextColumn("Validation Rule")
                }
            )
            
            st.download_button(
                label="💾 Save As Mapping Template (CSV)",
                data=edited_mapping_df.to_csv(index=False).encode('utf-8'),
                file_name="truealign_db_mapping_template.csv",
                mime="text/csv",
                key="pd_download_tpl"
            )
            
            st.markdown("---")
            if st.button("🚀 Push Validation Execution to Database", type="primary", use_container_width=True, key="pd_run"):
                if not pk_cols:
                    st.error("You must select at least one Primary Key before executing.")
                    st.stop()
                    
                with st.spinner('Translating AI rules into SQL and pushing the execution query down to the remote database...'):
                    new_mappings = []
                    rules_dict = {}
                    for index, row in edited_mapping_df.iterrows():
                        c1, c2, rule = str(row.get('File 1 Column')), str(row.get('File 2 Column')), str(row.get('Validation Rule (Optional)'))
                        if c1 and c2 and c1 != 'None' and c2 != 'None' and c1 != 'nan':
                            new_mappings.append(ColumnMap(file1_column=c1, file2_column=c2, validation_rule=rule if rule != 'nan' else None))
                            if rule and rule != 'nan':
                                rules_dict[c1] = rule
                    
                    final_config = ValidationConfig(primary_keys=pk_cols, column_mappings=new_mappings)
                    
                    from core.engines.sql_pushdown import SQLPushdownEngine
                    pushdown_engine = SQLPushdownEngine(final_config, rules_dict=rules_dict)
                    
                    try:
                        st.session_state.results = pushdown_engine.compare(conn_str_pd, pd_q1, pd_q2)
                        st.toast('Pushdown Execution Complete!', icon='🚀')
                    except Exception as e:
                        st.error(f"Remote Execution Failed: {str(e)}")
                        
            # Results UI
            if 'results' in st.session_state:
                res = st.session_state.results
                total1, total2 = res.get('Total Rows File 1', 0), res.get('Total Rows File 2', 0)
                mismatches = len(res.get('Data Mismatches', []))
                
                st.subheader("📊 Remote Database Execution Results")
                k1, k2, k3, k4, k5 = st.columns(5)
                k1.metric("Rows Scanned (Query 1)", f"{total1:,}")
                k2.metric("Rows Scanned (Query 2)", f"{total2:,}")
                k3.metric("Exact Matches", f"{len(res.get('Exact Matches', [])):,}")
                k4.metric("Missing Rows", f"{(len(res.get('Missing in File 1 (Found in 2)', [])) + len(res.get('Missing in File 2 (Found in 1)', []))):,}")
                k5.metric("Data Mismatches", f"{mismatches:,}")
                
                t1, t2, t3, t4 = st.tabs(["📝 Mismatch Report", "❌ Missing in 1", "❌ Missing in 2", "✅ Exact Matches"])
                with t1:
                    if mismatches > 0: st.dataframe(pd.DataFrame(res.get('Mismatch Breakdown', [])), use_container_width=True)
                    else: st.success("No validation errors found!")
                with t2: st.dataframe(res.get('Missing in File 1 (Found in 2)', pd.DataFrame()), use_container_width=True)
                with t3: st.dataframe(res.get('Missing in File 2 (Found in 1)', pd.DataFrame()), use_container_width=True)
                with t4: st.dataframe(res.get('Exact Matches', pd.DataFrame()), use_container_width=True)
                
                from core.reporter import ExcelReporter
                reporter = ExcelReporter()
                excel_bytes = reporter.generate_excel_report(res)
                st.download_button(
                    label="📥 Download Exceptions Report (Excel)",
                    data=excel_bytes,
                    file_name="TrueAlign_DB_Audit.xlsx",
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    type="primary",
                    use_container_width=True,
                    key="pd_excel"
                )
                
                st.markdown("<br>", unsafe_allow_html=True)
                if st.button("🔄 Start New Validation (Bottom)", use_container_width=True, key="pd_reset"):
                    reset_app()
