from typing import Any

import streamlit as st

from sheets import load_sessions, load_tasks


def render_sessions_tab(topics: list[dict[str, Any]]) -> None:
    st.header("Сессии")

    try:
        sessions = load_sessions()
        tasks = load_tasks()

        if not sessions:
            st.info("Сессий пока нет.")
            return

        for session in sorted(sessions, key=lambda s: s["started_at"], reverse=True):
            session_tasks = [
                task for task in tasks
                if task["session_id"] == session["session_id"]
            ]
            answered_count = len([
                task for task in session_tasks
                if task.get("status") == "answered"
            ])

            topic_title = next(
                (
                    topic["title"]
                    for topic in topics
                    if topic["id"] == session["topic_id"]
                ),
                session["topic_id"],
            )

            st.write(
                f"**{topic_title}** — день {session['repetition_day']} — "
                f"{session['scheduled_date']} — "
                f"{answered_count}/{len(session_tasks)} задач — статус `{session['status']}`"
            )
    except Exception as e:
        st.error("Не удалось прочитать сессии.")
        st.code(str(e))

