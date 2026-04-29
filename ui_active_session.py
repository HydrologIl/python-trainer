import streamlit as st

from sheets import load_sessions
from ui_today import render_active_session


def render_active_session_top(topics: list[dict]) -> None:
    current_session_id = st.session_state.get("current_session_id")
    active_source = st.session_state.get("active_session_source")

    if not current_session_id:
        return

    # Обычные сессии из вкладки “Сегодня” оставляем во вкладке “Сегодня”.
    # Наверх выносим только сессии, открытые из “Сессии” или “Слабые места”,
    # потому что именно они на телефоне схлопывались при rerun.
    if active_source not in ["sessions", "weak_spots"]:
        return

    try:
        sessions = load_sessions()
    except Exception as e:
        st.warning("Не удалось загрузить активную сессию.")
        st.code(str(e))
        return

    current_session = next(
        (
            session for session in sessions
            if session.get("session_id") == current_session_id
        ),
        None,
    )

    if not current_session:
        return

    topic_by_id = {
        topic["id"]: topic
        for topic in topics
    }

    current_topic = topic_by_id.get(current_session.get("topic_id"))

    if not current_topic:
        return

    st.markdown("## Активная сессия")

    if active_source == "weak_spots":
        st.caption("Открыта тренировка “Слабые места”.")
    elif active_source == "sessions":
        st.caption("Открыта из списка сессий.")

    render_active_session(current_topic, current_session)
    st.markdown("---")
