"""Session state, model catalogue and navigation helpers."""
import os

import streamlit as st

# Display name -> (LiteLLM model string, provider API key name).
# Provider prefixes make LiteLLM's routing explicit. Checked against LiteLLM's model map on 2026-09-26;
# retired models (Gemini 1.5, GPT-4o, o1, Claude 3.x, Groq LLaMA 3, Mixtral) were removed.
AVAILABLE_MODELS = {
    "Google Gemini 3.8 Flash": ("gemini/gemini-3.8-flash", "GEMINI_API_KEY"),
    "Google Gemini 3.1 Pro (Preview)": ("gemini/gemini-3.1-pro-preview", "GEMINI_API_KEY"),
    "Google Gemini 2.5 Pro": ("gemini/gemini-2.5-pro", "GEMINI_API_KEY"),
    "OpenAI GPT-5.6": ("openai/gpt-5.6", "OPENAI_API_KEY"),
    "OpenAI GPT-5.4 Mini": ("openai/gpt-5.4-mini", "OPENAI_API_KEY"),
    "Anthropic Claude Opus 5": ("anthropic/claude-opus-5", "ANTHROPIC_API_KEY"),
    "Anthropic Claude Sonnet 5": ("anthropic/claude-sonnet-5", "ANTHROPIC_API_KEY"),
    "Anthropic Claude Haiku 4.5": ("anthropic/claude-haiku-4-5", "ANTHROPIC_API_KEY"),
    "Groq GPT-OSS 120B": ("groq/openai/gpt-oss-120b", "GROQ_API_KEY"),
    "Mistral Large": ("mistral/mistral-large-latest", "MISTRAL_API_KEY"),
    "Mistral Medium": ("mistral/mistral-medium-latest", "MISTRAL_API_KEY"),
    "Cohere Command A+": ("cohere_chat/command-a-plus-05-2026", "COHERE_API_KEY"),
}
PROVIDER_KEYS = sorted({key for _, key in AVAILABLE_MODELS.values()})
DEFAULT_MODELS = {"GEMINI_API_KEY": "Google Gemini 3.8 Flash", "OPENAI_API_KEY": "OpenAI GPT-5.6",
                  "ANTHROPIC_API_KEY": "Anthropic Claude Opus 5"}

# Per-run workflow state, cleared on restart or when switching tiers
WORKFLOW_KEYS = ["ai_config", "results", "config_signature", "is_template_loaded", "column_cache", "grid_draft"]


def init_state():
    ss = st.session_state
    if "stored_keys" not in ss:
        # Keys configured by the server admin are read (not written) from the environment;
        # each user's own keys live only in their session.
        ss.stored_keys = {k: os.environ.get(k, "") for k in PROVIDER_KEYS}
    if "user_configured_models" not in ss:
        ss.user_configured_models = [m for k, m in DEFAULT_MODELS.items() if os.environ.get(k)]
    ss.setdefault("user", None)
    ss.setdefault("is_guest", False)
    ss.setdefault("uploader_key", 0)
    ss.setdefault("config_version", 0)
    ss.setdefault("grid_version", 0)
    ss.setdefault("ai_config", None)
    ss.setdefault("execution_tier", None)


def sync_auth_with_url():
    """Keep login state and ?auth= in sync so the browser Back button behaves."""
    ss = st.session_state
    auth_param = st.query_params.get("auth")
    if auth_param == "guest":
        ss.is_guest = True
    elif auth_param == "user" and not ss.user:
        del st.query_params["auth"]  # URL says user but the session was lost (e.g. app restart)
    elif not auth_param and (ss.is_guest or ss.user):
        if len(st.query_params) == 0:
            ss.is_guest = False  # back to the bare root URL: log out
            ss.user = None
            st.rerun()
        else:
            st.query_params["auth"] = "user" if ss.user else "guest"


def clear_workflow():
    for k in WORKFLOW_KEYS:
        st.session_state.pop(k, None)
    st.session_state.ai_config = None


def set_config(config, from_template: bool = False):
    """Store a new mapping; bumping the version resets the grid editor's widget state."""
    st.session_state.ai_config = config
    st.session_state.is_template_loaded = from_template
    st.session_state.config_version += 1
    st.session_state.pop("grid_draft", None)
    st.session_state.pop("results", None)


def reset_app():
    clear_workflow()
    st.session_state.pop("execution_tier", None)
    st.session_state.uploader_key += 1  # new widget keys clear the file uploaders
    current_auth = "user" if st.session_state.user else ("guest" if st.session_state.is_guest else None)
    st.query_params.clear()
    if current_auth:
        st.query_params["auth"] = current_auth
    st.rerun()
