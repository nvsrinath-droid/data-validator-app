import streamlit as st


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
    /* Keep Streamlit App Header Transparent but Visible */
    .stApp > header {
        background-color: transparent !important;
    }

    /* Hide Streamlit Default Footer */
    footer {visibility: hidden;}

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
    [data-testid="stAppViewBlockContainer"] {
        padding-top: 0rem !important;
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
        background-color: #334155 !important;
        border: 1px solid rgba(255, 255, 255, 0.3) !important;
        border-radius: 12px !important;
        color: white !important;
        transition: border-color 0.2s ease, box-shadow 0.2s ease;
    }
    
    .stTextInput>div>div>input:focus, .stSelectbox>div>div>div:focus, .stTextArea>div>div>textarea:focus {
        border-color: #3b82f6 !important;
        box-shadow: 0 0 0 1px #3b82f6 !important;
    }

    /* Text inside Inputs */
    .stTextInput>div>div>input::placeholder, .stTextArea>div>div>textarea::placeholder {
        color: #94a3b8 !important;
    }

    /* Hide 'Press Enter to Submt' helper text on forms */
    [data-testid="InputInstructions"] {
        display: none !important;
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
        gap: 12px;
        background-color: rgba(15, 23, 42, 0.6);
        padding: 10px;
        border-radius: 16px;
        border: 1px solid rgba(255, 255, 255, 0.1);
        display: flex;
        justify-content: center;
        align-items: stretch;
    }
    .stTabs [data-baseweb="tab"] {
        background-color: transparent;
        border-radius: 12px;
        color: #94a3b8 !important;
        border: none !important;
        font-size: 1.05rem !important;
        padding: 14px 24px !important;
        flex: 1;
        display: flex;
        justify-content: center;
        transition: all 0.2s ease;
    }
    .stTabs [data-baseweb="tab"]:hover {
        background-color: rgba(255, 255, 255, 0.05);
        color: #e2e8f0 !important;
    }
    .stTabs [aria-selected="true"] {
        background-color: #3b82f6 !important;
        color: white !important;
        box-shadow: 0 4px 15px rgba(59, 130, 246, 0.3) !important;
        font-weight: 600 !important;
    }

    /* Info/Warning/Error boxes and Tier Cards */
    .stAlert {
        background-color: rgba(15, 23, 42, 0.5) !important;
        backdrop-filter: blur(16px) !important;
        -webkit-backdrop-filter: blur(16px) !important;
        border-radius: 16px !important;
        border: 1px solid rgba(255, 255, 255, 0.08) !important;
        color: #f8fafc !important;
    }

    .tier-card {
        background: linear-gradient(180deg, rgba(30, 41, 59, 0.8) 0%, rgba(15, 23, 42, 0.6) 100%);
        border: 1px solid rgba(255, 255, 255, 0.1);
        border-radius: 16px;
        padding: 24px;
        min-height: 250px;
        margin-bottom: 20px;
        transition: all 0.3s ease;
        box-shadow: 0 10px 25px -5px rgba(0, 0, 0, 0.3);
    }
    .tier-card:hover {
        border-color: rgba(255, 255, 255, 0.3);
        transform: translateY(-2px);
    }
    .tier-card h3 {
        margin-top: 0;
        font-size: 1.25rem !important;
        color: #f8fafc !important;
    }
    .tier-card p {
        color: #94a3b8;
        font-size: 0.95rem;
        margin-bottom: 1rem;
    }
    .tier-card ul {
        padding-left: 20px;
        margin-top: 16px;
    }
    .tier-card li {
        margin-bottom: 8px;
        color: #cbd5e1;
        font-size: 0.95rem;
    }
    .tier-standard { border-top: 4px solid #3b82f6; }
    .tier-heavy { border-top: 4px solid #10b981; }
    .tier-enterprise { border-top: 4px solid #8b5cf6; }
    
    /* Streamlit Dialog Modal */
    div[role="dialog"] {
        background: linear-gradient(135deg, #1e293b 0%, #0f172a 100%) !important;
        border: 1px solid rgba(255,255,255,0.1);
        border-radius: 24px;
        box-shadow: 0 25px 50px -12px rgba(0, 0, 0, 0.5);
    }
    
    /* File Uploader styling */
    [data-testid="stFileUploadDropzone"] {
        background: rgba(255, 255, 255, 0.08) !important;
        border: 2px dashed rgba(255, 255, 255, 0.3) !important;
        border-radius: 16px !important;
        padding: 30px 20px !important;
        transition: all 0.3s cubic-bezier(0.4, 0, 0.2, 1) !important;
    }
    [data-testid="stFileUploadDropzone"]:hover {
        background: rgba(255, 255, 255, 0.12) !important;
        border-color: #3b82f6 !important;
        box-shadow: 0 4px 15px rgba(59, 130, 246, 0.2) !important;
        transform: translateY(-2px);
    }
    [data-testid="stFileUploadDropzone"] button {
        background: linear-gradient(135deg, #3b82f6 0%, #2563eb 100%) !important;
        border: none !important;
        border-radius: 8px !important;
        color: white !important;
        font-weight: 500 !important;
    }
    [data-testid="stFileUploadDropzone"] svg {
        fill: #3b82f6 !important;
        color: #3b82f6 !important;
    }
    
    /* Hide the generic Streamlit "Limit 200MB per file" subtext under the uploader since it conflicts with business tier logic */
    [data-testid="stFileUploadDropzone"] small {
        display: none !important;
    }
    
    /* Labels */
    label, label p, label div {
        color: #cbd5e1 !important;
        font-weight: 500 !important;
    }

    </style>
    """, unsafe_allow_html=True)
