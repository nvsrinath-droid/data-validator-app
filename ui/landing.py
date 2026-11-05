import streamlit as st


def open_tier(tier: str):
    st.session_state.execution_tier = tier
    st.query_params["engine"] = tier
    st.rerun()


def render_landing():
    st.markdown("---")
    st.markdown("<h2 style='text-align: center; margin-bottom: 0.5rem;'>✨ Unleash AI on Your Data Validation</h2>", unsafe_allow_html=True)
    st.markdown("<p style='text-align: center; color: #94a3b8; margin-bottom: 2.5rem;'>Choose the processing tier that deeply matches your data volume and source.</p>", unsafe_allow_html=True)

    c1, c2, c3 = st.columns(3)
    with c1:
        st.markdown("""
        <div class="tier-card tier-standard">
            <h3>🚀 Standard Data Files</h3>
            <p>Perfect for everyday data validation tasks.</p>
            <ul>
                <li>Fast In-Memory Processing</li>
                <li>Upload Excel/CSV up to ~50MB</li>
                <li>Run DB Queries up to ~100k rows</li>
            </ul>
        </div>
        """, unsafe_allow_html=True)
        if st.button("Launch Standard Engine", type="primary", width="stretch"):
            open_tier("standard")

    with c2:
        st.markdown("""
        <div class="tier-card tier-heavy">
            <h3>🏢 Massive Data Files</h3>
            <p>For massive flat-file datasets.</p>
            <ul>
                <li>Advanced Disk Streaming System</li>
                <li>Avoids memory bottlenecks completely</li>
                <li>Parses Gigabyte-scale local flat files</li>
            </ul>
        </div>
        """, unsafe_allow_html=True)
        if st.button("Launch Massive Engine", type="primary", width="stretch"):
            open_tier("heavy")

    with c3:
        st.markdown("""
        <div class="tier-card tier-enterprise">
            <h3>🌐 Enterprise SQL Warehouses</h3>
            <p>For enterprise DB infrastructure.</p>
            <ul>
                <li>Zero data downloading required</li>
                <li>Translates AI rules organically to SQL</li>
                <li>Infinite remote DB scale</li>
            </ul>
        </div>
        """, unsafe_allow_html=True)
        if st.button("Launch Enterprise Engine", type="primary", width="stretch"):
            open_tier("pushdown")

    st.markdown("---")
    st.subheader("We'd Love to Hear From You")
    st.markdown("Have feedback, feature requests, or need enterprise support? Let us know!")

    with st.form("feedback_form", clear_on_submit=True):
        c_name, c_email, c_phone = st.columns(3)
        f_name = c_name.text_input("Name")
        f_email = c_email.text_input("Email")
        f_phone = c_phone.text_input("Phone Number")
        f_msg = st.text_area("Message / Feedback", height=100)

        if st.form_submit_button("📨 Send Feedback", type="primary"):
            if f_msg and (f_email or f_phone):
                # Route simulated backend payload
                print(f"--- NEW APP FEEDBACK ---\nTo: info@strategyeagles.com\nFrom: {f_name} ({f_email} | {f_phone})\nMessage: {f_msg}\n------------------------")
                st.success("Thank you! We have received your feedback. Someone from our team will reach out to you soon if you have requested help.")
            else:
                st.error("Please provide at least your email or phone and a message.")
