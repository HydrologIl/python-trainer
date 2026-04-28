from typing import Any

import streamlit as st

from sheets import load_sessions, load_tasks
from ui_common import load_session_into_state
from ui_today import render_active_session


def render_sessions_tab(topics: list[dict[str, Any]]) -> None:
    st.header("Сессии")

    try:
        sessions = load_sessions()
        tasks = load_tasks()

        if not sessions:
            st.info("Сессий пока нет.")
            return

        topic_by_id = {
            topic["id"]: topic
            for topic in topics
        }

        current_session_id = st.session_state.get("current_session_id")

        if current_session_id:
            current_session = next(
                (
                    session for session in sessions
                    if session["session_id"] == current_session_id
                ),
                None,
            )

            if (
                current_session
                and st.session_state.get("active_session_source") == "sessions"
            ):
                current_topic = topic_by_id.get(current_session["topic_id"])

                if current_topic:
                    st.subheader("Открытая сессия")
                    render_active_session(current_topic, current_session)
                    st.markdown("---")

        st.subheader("Все сессии")

        for session in sorted(sessions, key=lambda s: s["started_at"], reverse=True):
            session_tasks = [
                task for task in tasks
                if task["session_id"] == session["session_id"]
            ]

            answered_count = len([
                task for task in session_tasks
                if task.get("status") == "answered"
            ])

            skipped_count = len([
                task for task in session_tasks
                if task.get("status") == "skipped"
            ])

            bad_count = len([
                task for task in session_tasks
                if task.get("status") == "bad_task"
            ])

            topic = topic_by_id.get(session["topic_id"])
            topic_title = topic["title"] if topic else session["topic_id"]

            repetition_label = (
                "слабое место"
                if session["repetition_day"] == -1
                else f"день {session['repetition_day']}"
            )

            col_info, col_action = st.columns([4, 1])

            with col_info:
                st.write(
                    f"**{topic_title}** — {repetition_label} — "
                    f"{session['scheduled_date']} — "
                    f"{answered_count}/{len(session_tasks)} задач — "
                    f"пропущено: {skipped_count}, плохих: {bad_count} — "
                    f"статус `{session['status']}`"
                )

            with col_action:
                can_continue = (
                    session["status"] != "completed"
                    and len(session_tasks) > 0
                )

                if st.button(
                    "Продолжить",
                    key=f"continue_session_{session['session_id']}",
                    disabled=not can_continue,
                ):
                    load_session_into_state(session)
                    st.session_state["selected_topic_id"] = session["topic_id"]
                    st.session_state["selected_repetition_day"] = session["repetition_day"]
                    st.session_state["active_session_source"] = "sessions"
                    st.rerun()

    except Exception as e:
        st.error("Не удалось прочитать сессии.")
        st.code(str(e))
