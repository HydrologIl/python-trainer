from typing import Any

import streamlit as st

from sheets import load_sessions, load_tasks
from ui_common import load_session_into_state


def is_session_completed(session: dict[str, Any], session_tasks: list[dict[str, Any]]) -> bool:
    if session.get("status") == "completed":
        return True

    if not session_tasks:
        return False

    closed_statuses = {"answered", "correct", "skipped", "bad_task"}
    return all(task.get("status") in closed_statuses for task in session_tasks)


def render_session_row(
    session: dict[str, Any],
    session_tasks: list[dict[str, Any]],
    topic_title: str,
    disabled_continue: bool,
    key_prefix: str,
) -> None:
    answered_count = len([
        task for task in session_tasks
        if task.get("status") in ["answered", "correct", "partially_correct", "incorrect"]
    ])

    correct_count = len([
        task for task in session_tasks
        if task.get("status") in ["answered", "correct"]
    ])

    skipped_count = len([
        task for task in session_tasks
        if task.get("status") == "skipped"
    ])

    bad_count = len([
        task for task in session_tasks
        if task.get("status") == "bad_task"
    ])

    remaining_count = max(0, len(session_tasks) - correct_count - skipped_count - bad_count)

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
            f"зачтено: {correct_count}/{len(session_tasks)}, "
            f"попыток: {answered_count}, "
            f"осталось: {remaining_count}, "
            f"пропущено: {skipped_count}, плохих: {bad_count} — "
            f"статус `{session['status']}`"
        )

    with col_action:
        can_continue = (
            not disabled_continue
            and session["status"] != "completed"
            and len(session_tasks) > 0
        )

        if st.button(
            "Продолжить",
            key=f"{key_prefix}_continue_session_{session['session_id']}",
            disabled=not can_continue,
        ):
            load_session_into_state(session)
            st.session_state["selected_topic_id"] = session["topic_id"]
            st.session_state["selected_repetition_day"] = session["repetition_day"]
            st.session_state["active_session_source"] = "sessions"
            st.rerun()


def render_sessions_group(
    sessions: list[dict[str, Any]],
    tasks: list[dict[str, Any]],
    topic_by_id: dict[str, dict[str, Any]],
    key_prefix: str,
    disabled_continue: bool = False,
) -> None:
    tasks_by_session: dict[str, list[dict[str, Any]]] = {}
    for task in tasks:
        tasks_by_session.setdefault(task["session_id"], []).append(task)

    for session in sessions:
        session_tasks = sorted(
            tasks_by_session.get(session["session_id"], []),
            key=lambda task: task.get("order", 0),
        )
        topic = topic_by_id.get(session["topic_id"])
        topic_title = topic["title"] if topic else session["topic_id"]

        render_session_row(
            session=session,
            session_tasks=session_tasks,
            topic_title=topic_title,
            disabled_continue=disabled_continue,
            key_prefix=key_prefix,
        )


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

        tasks_by_session: dict[str, list[dict[str, Any]]] = {}
        for task in tasks:
            tasks_by_session.setdefault(task["session_id"], []).append(task)

        sorted_sessions = sorted(
            sessions,
            key=lambda session: session.get("started_at", ""),
            reverse=True,
        )

        active_sessions = []
        completed_sessions = []

        for session in sorted_sessions:
            session_tasks = tasks_by_session.get(session["session_id"], [])
            if is_session_completed(session, session_tasks):
                completed_sessions.append(session)
            else:
                active_sessions.append(session)

        st.subheader(f"Активные сессии ({len(active_sessions)})")
        if active_sessions:
            render_sessions_group(
                active_sessions,
                tasks,
                topic_by_id,
                key_prefix="active",
            )
        else:
            st.info("Активных сессий нет.")

        with st.expander(f"Завершённые сессии ({len(completed_sessions)})", expanded=False):
            if completed_sessions:
                render_sessions_group(
                    completed_sessions,
                    tasks,
                    topic_by_id,
                    key_prefix="completed",
                    disabled_continue=True,
                )
            else:
                st.caption("Завершённых сессий пока нет.")

    except Exception as e:
        st.error("Не удалось прочитать сессии.")
        st.code(str(e))
