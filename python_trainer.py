import os

try:
    import streamlit as st

    app_mode = str(st.secrets.get("APP_MODE", os.getenv("APP_MODE", "legacy"))).lower()
except Exception:
    app_mode = os.getenv("APP_MODE", "legacy").lower()

if app_mode == "universal":
    from learning_app.streamlit_app import run_universal_app

    run_universal_app()
else:
    from legacy_app import run_legacy_app

    run_legacy_app()
