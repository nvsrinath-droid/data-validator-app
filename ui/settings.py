import os

import streamlit as st

from .state import AVAILABLE_MODELS


@st.dialog("⚙️ Global AI Settings & API Keys")
def settings_modal():
    st.markdown("Add the AI models you want to use. API keys are kept only in your browser session.")

    c_add_1, c_add_2 = st.columns([3, 1])
    with c_add_1:
        available_to_add = [m for m in AVAILABLE_MODELS if m not in st.session_state.user_configured_models]
        model_to_add = st.selectbox("Select a model to add", available_to_add, label_visibility="collapsed")
    with c_add_2:
        if st.button("➕ Add Model", width="stretch", disabled=not available_to_add):
            if model_to_add:
                st.session_state.user_configured_models.append(model_to_add)
                st.rerun()

    st.markdown("---")

    with st.container(height=350):
        if not st.session_state.user_configured_models:
            st.info("No AI models configured yet. Please add one from the dropdown above.")

        for idx, model_name in enumerate(st.session_state.user_configured_models):
            _, required_env_key = AVAILABLE_MODELS[model_name]
            provider_name = required_env_key.split('_')[0].title()

            c_label, c_remove = st.columns([4, 1])
            c_label.markdown(f"**{model_name}**")
            if c_remove.button("🗑️ Remove", key=f"rm_{model_name}_{idx}"):
                st.session_state.user_configured_models.remove(model_name)
                st.rerun()

            global_val = os.environ.get(required_env_key, "")
            current_val = st.session_state.stored_keys.get(required_env_key, "")
            if global_val and current_val == global_val:
                st.info("✅ Securely provided by Administrator/Global Env.")
            else:
                new_val = st.text_input(
                    f"{provider_name} API Key",
                    value=current_val,
                    type="password",
                    key=f"input_{required_env_key}_{idx}",
                    label_visibility="collapsed",
                    placeholder=f"Enter {required_env_key}",
                )
                if new_val != current_val:
                    st.session_state.stored_keys[required_env_key] = new_val

            st.divider()

    if st.button("Save & Close", type="primary", width="stretch"):
        st.rerun()
