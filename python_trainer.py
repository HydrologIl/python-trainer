import streamlit as st

from sheets import load_topics
from ui import (
    reset_session,
    render_sidebar,
    render_today_tab,
    render_plan_tab,
    render_sessions_tab,
    render_progress_tab,
    render_weak_spots_tab,
)


st.set_page_config(page_title="Python Trainer", page_icon="🐍", layout="centered")

st.title("Python Trainer")
st.write("Google Sheets как база + удобная сессия + прогресс и ошибки.")

today_value = render_sidebar()

try:
    topics = load_topics()
except Exception as e:
    st.error("Не удалось прочитать Google Sheet.")
    st.write(
        "Если видишь 429 quota exceeded — это лимит чтения Google Sheets. "
        "Подожди 1–2 минуты и нажми «Перечитать Google Sheet». "
        "Чтение кэшируется на 60 секунд."
    )
    st.code(str(e))
    st.stop()

tab_today, tab_plan, tab_sessions, tab_progress, tab_weak_spots = st.tabs(
    ["Сегодня", "Учебный план", "Сессии", "Прогресс", "Слабые места"]
)

with tab_plan:
    render_plan_tab(topics, today_value)

with tab_sessions:
    render_sessions_tab(topics)

with tab_progress:
    render_progress_tab(topics, today_value)

with tab_weak_spots:
    render_weak_spots_tab(topics, today_value)

with tab_today:
    render_today_tab(topics, today_value)
