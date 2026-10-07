def run_legacy_app() -> None:
    import streamlit as st

    from sheets import load_topics
    from ui import (
        render_active_session_top,
        render_datasets_tab,
        render_plan_tab,
        render_progress_tab,
        render_sessions_tab,
        render_sidebar,
        render_today_tab,
        render_weak_spots_tab,
    )

    st.set_page_config(page_title="Python Trainer", page_icon="🐍", layout="centered")
    st.title("Python Trainer")
    st.write("Google Sheets как база + удобная сессия + прогресс и ошибки.")

    today_value = render_sidebar()
    try:
        topics = load_topics()
    except Exception as exc:
        st.error("Не удалось прочитать Google Sheet.")
        st.write(
            "Если видишь 429 quota exceeded — это лимит чтения Google Sheets. "
            "Подожди 1–2 минуты и нажми «Перечитать Google Sheet»."
        )
        st.code(str(exc))
        st.stop()

    render_active_session_top(topics)
    tabs = st.tabs(
        ["Сегодня", "Учебный план", "Сессии", "Прогресс", "Слабые места", "Датасеты"]
    )
    with tabs[1]:
        render_plan_tab(topics, today_value)
    with tabs[2]:
        render_sessions_tab(topics)
    with tabs[3]:
        render_progress_tab(topics, today_value)
    with tabs[4]:
        render_weak_spots_tab(topics, today_value)
    with tabs[5]:
        render_datasets_tab()
    with tabs[0]:
        render_today_tab(topics, today_value)
