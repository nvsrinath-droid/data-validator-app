import streamlit as st
import pandas as pd
import json
import base64
import os
from dotenv import load_dotenv

# App layout and styling must be set first
st.set_page_config(page_title="AI Data Validator", page_icon="🕵️", layout="wide")

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
from ai.agent import GeminiAgent
from core.schemas import ValidationConfig, ColumnMap
from core.comparator import DataComparator

# Load ENV logic specifically for the web app missing a .env
load_dotenv()
api_key = os.environ.get("GEMINI_API_KEY")

# --- Sidebar Configuration ---
with st.sidebar:
    st.image("https://cdn-icons-png.flaticon.com/512/3208/3208076.png", width=50) # Generic data icon
    st.title("Settings")
    
    if not api_key:
        api_key_input = st.text_input("Enter Gemini API Key", type="password", help="Get this from Google AI Studio")
        if api_key_input:
            api_key = api_key_input
            os.environ["GEMINI_API_KEY"] = api_key
    else:
        st.success("API Key Loaded!")
        
    st.markdown("---")
    st.markdown("**How to use:**\n1. Upload your two files.\n2. Review the AI's mapping guesses.\n3. Run the validation report!")

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
colA, colB = st.columns([3, 1])
with colA:
    st.title("🕵️ Intelligent Data Validator")
    st.markdown("Easily find missing rows and mismatched values between any two spreadsheets using the power of Google Gemini.")
with colB:
    st.markdown("<br>", unsafe_allow_html=True)
    if st.button("🔄 Start New Validation", use_container_width=True):
        reset_app()

# Step 1: Upload Files
col1, col2 = st.columns(2)
with col1:
    st.subheader("📁 Source File (System of Record)")
    file1 = st.file_uploader("Upload File 1", type=["csv", "xlsx"], key=f"file1_{st.session_state.uploader_key}")

with col2:
    st.subheader("📄 External File (To Compare)")
    file2 = st.file_uploader("Upload File 2", type=["csv", "xlsx"], key=f"file2_{st.session_state.uploader_key}")

if file1 and file2:
    if not api_key:
         st.warning("Please provide a Gemini API Key in the sidebar to continue.")
         st.stop()
         
    # Init connectors
    conn1 = FileConnector(file1)
    conn2 = FileConnector(file2)
    
    st.markdown("---")
    st.subheader("🧠 Step 2: AI Schema Mapping")
    
    # Generate Config Button
    if st.button("✨ Analyze Files with Gemini", type="primary"):
        with st.spinner('Gemini is reading your spreadsheets and building a mapping schema...'):
            try:
                sample1 = conn1.get_sample_data(5).to_csv(index=False)
                sample2 = conn2.get_sample_data(5).to_csv(index=False)
                
                agent = GeminiAgent(api_key=api_key)
                st.session_state.ai_config = agent.suggest_configuration(sample1, sample2)
                st.success("Analysis Complete!")
            except Exception as e:
                st.error(f"Error during AI analysis: {str(e)}")
                
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
        
        mapping_data = [{"File 1 Column": m.file1_column, "File 2 Column": m.file2_column} for m in config.column_mappings]
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
                )
            }
        )
        st.markdown("---")
        # --- Step 3: Run Comparison ---
        if st.button("🚀 Run Full Data Comparison", type="primary", use_container_width=True):
            with st.spinner('Comparing all rows...'):
                # Rebuild config object from the UI edited state, safely dropping empty/deleted rows
                new_mappings = []
                for index, row in edited_mapping_df.iterrows():
                    c1 = str(row.get('File 1 Column', '')).strip()
                    c2 = str(row.get('File 2 Column', '')).strip()
                    # Only map if both columns are provided and not NaN
                    if c1 and c2 and c1.lower() != 'nan' and c2.lower() != 'nan' and c1 != 'None' and c2 != 'None':
                        new_mappings.append(ColumnMap(file1_column=c1, file2_column=c2))
                
                final_config = ValidationConfig(
                    primary_keys=pk_cols,
                    column_mappings=new_mappings,
                    ignore_columns=[]
                )
                
                # Execute Core Logic
                comparator = DataComparator(final_config)
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
            # We need a helper to generate CSV strings for download
            def to_csv_download(data_dict_list, is_mismatch=False):
                if not data_dict_list: return None
                
                if is_mismatch:
                     # Flatten mismatch structure
                     flat_data = []
                     for item in data_dict_list:
                        pk_str = str(item["primary_keys"])
                        for diff in item["differences"]:
                            flat_data.append({
                                "Primary Key": pk_str,
                                "Column": diff["column"],
                                "File 1 Value": diff["file1_value"],
                                "File 2 Value": diff["file2_value"]
                            })
                     return pd.DataFrame(flat_data).to_csv(index=False).encode('utf-8')
                else:
                     return pd.DataFrame(data_dict_list).to_csv(index=False).encode('utf-8')

            # Create tabs for clean viewing
            tab1, tab2, tab3 = st.tabs(["Mismatched Values", "Missing in Source", "Missing in External"])
            
            with tab1:
                mismatches = results.get('mismatches', [])
                st.metric("Total Mismatched Rows", len(mismatches))
                if mismatches:
                    csv_data = to_csv_download(mismatches, is_mismatch=True)
                    st.download_button("Download Mismatches CSV", data=csv_data, file_name="mismatches.csv", mime="text/csv")
                    st.dataframe(pd.DataFrame(mismatches).astype(str)) # Easy viewer
            
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
