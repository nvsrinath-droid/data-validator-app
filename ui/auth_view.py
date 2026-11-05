import streamlit as st

import core.auth as auth

from .settings import settings_modal
from .state import reset_app


def render_header():
    col_title, col_settings, col_auth, col_reset = st.columns([5.5, 1, 1.2, 1.2])

    with col_title:
        st.markdown("<div style='margin-top: 0px;'><a href='/' target='_self' style='text-decoration: none;'><h1 style='display:inline; margin: 0; padding: 0;'>🎯 TrueAlign Data</h1></a>", unsafe_allow_html=True)
        st.markdown("<p style='margin-top: 5px; margin-bottom: 0; color: #cbd5e1; font-size: 1.1rem;'>Easily find missing rows, map mismatched schemas, and enforce custom business rules between live databases and flat files using the power of AI.</p></div>", unsafe_allow_html=True)

    with col_settings:
        st.markdown("<div style='height: 15px;'></div>", unsafe_allow_html=True)
        if st.button("⚙️ Settings", width="stretch"):
            settings_modal()
    with col_auth:
        st.markdown("<div style='height: 15px;'></div>", unsafe_allow_html=True)
        if st.session_state.user or st.session_state.is_guest:
            if st.button("🚪 Logout", width="stretch"):
                st.session_state.user = None
                st.session_state.is_guest = False
                st.query_params.clear()
                st.rerun()
    with col_reset:
        st.markdown("<div style='height: 15px;'></div>", unsafe_allow_html=True)
        if st.button("🔄 Restart", width="stretch", help="Restart the validation session"):
            reset_app()


def require_login():
    """Show login / register / guest options and stop the script until the user picks one."""
    if st.session_state.user or st.session_state.is_guest:
        return

    st.markdown("---")
    st.markdown("<h2 style='text-align: center; margin-bottom: 2.5rem;'>✨ Welcome to TrueAlign Data Validation</h2>", unsafe_allow_html=True)

    c_login, _, c_reg = st.columns([4, 1, 4])

    with c_login:
        st.subheader("Login to Your Account")
        with st.form("login_form"):
            email_login = st.text_input("Email")
            pass_login = st.text_input("Password (case sensitive)", type="password")
            if st.form_submit_button("Log In", type="primary", width="stretch"):
                if auth.authenticate_user(email_login, pass_login):
                    st.session_state.user = email_login
                    st.query_params["auth"] = "user"
                    st.rerun()
                else:
                    st.error("Invalid email or password.")

        st.markdown("<br>", unsafe_allow_html=True)
        if st.button("👋 Continue as Guest", width="stretch"):
            st.session_state.is_guest = True
            st.query_params["auth"] = "guest"
            st.rerun()

    with c_reg:
        st.subheader("Create a Free Account")
        st.info("Registered users can securely save their AI mapping templates for future pipelines.")
        with st.form("register_form", clear_on_submit=True):
            email_reg = st.text_input("Email")
            pass_reg = st.text_input("Password (case sensitive)", type="password")
            if st.form_submit_button("Register", type="primary", width="stretch"):
                if email_reg and pass_reg:
                    if auth.register_user(email_reg, pass_reg):
                        st.success("Registration successful! You may now log in.")
                    else:
                        st.error("Email already exists.")
                else:
                    st.error("Please fill out both fields.")

    st.markdown("---")
    st.markdown("<p style='text-align:center; color:#94a3b8; font-size:0.9rem;'>Google/Apple Sign-In integration is pending Developer Key approval from Identity Providers.</p>", unsafe_allow_html=True)
    st.stop()
