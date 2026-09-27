"""Session state, model catalogue and navigation helpers."""
import os

import streamlit as st

# Display name -> (litellm model string, provider API key name)
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
    "Mistral Large": ("mistral/mistral-large-latest", "MISTRAL_API_KEY"),
}
PROVIDER_KEYS = sorted({key for _, key in AVAILABLE_MODELS.values()})
DEFAULT_MODELS = {"GEMINI_API_KEY": "Google Gemini 2.5 Flash", "OPENAI_API_KEY": "OpenAI GPT-4o",
                  "ANTHROPIC_API_KEY": "Anthropic Claude 3.5 Sonnet"}

# Per-run workflow state, cleared on restart or when switching tiers
WORKFLOW_KEYS = ["ai_config", "results", "config_signature", "is_template_loaded", "column_cache"]


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
