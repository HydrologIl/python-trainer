from datetime import date
from typing import Any

import streamlit as st

from gemini_service import FALLBACK_MODELS
from scheduler import REPETITION_DAYS
from sheets import get_first_unanswered_index, get_tasks_for_session


def reset_session() -> None:
    for key in [
        "current_session_id",
        "tasks",
        "current_task_index",
        "selected_topic_id",
        "selected_repetition_day",
        "last_feedback",
        "last_verdict",
        "user_answer",
        "answer_input",
        "active_session_source",
    ]:
        if key in st.session_state:
            del st.session_state[key]


def render_sidebar() -> date:
    with st.sidebar:
        st.header("Настройки")

        today_value = st.date_input(
            "Дата для расчёта повторений",
            value=date.today(),
            help="Можно поставить другую дату, чтобы проверить будущие или прошлые повторения.",
        )

        if st.button("Сбросить текущий экран"):
            reset_session()
            st.rerun()

        if st.button("Перечитать Google Sheet"):
            st.cache_data.clear()
            st.cache_resource.clear()
            reset_session()
            st.rerun()

        st.markdown("---")
        st.caption(f"Дни повторения: {', '.join(str(day) for day in REPETITION_DAYS)}.")
        st.caption(f"Модели Gemini: {', '.join(FALLBACK_MODELS)}")

    return today_value


def render_task(task: dict[str, Any], index: int, total: int) -> None:
    task_type_labels = {
        "debug": "Исправление ошибок",
        "output_prediction": "Что выведет код?",
        "write_code": "Написание кода",
    }

    task_type = task_type_labels.get(task.get("type"), task.get("type", "Задача"))

    st.markdown(f"### Задача {index + 1} из {total}")
    st.caption(
        f"{task_type} · сложность: {task.get('difficulty', 'не указана')} · "
        f"статус: {task.get('status', 'new')}"
    )

    st.write(task.get("task", ""))

    if task.get("code"):
        st.code(task["code"], language="python")


def load_session_into_state(session: dict[str, Any]) -> None:
    tasks = get_tasks_for_session(session["session_id"])
    current_index = get_first_unanswered_index(tasks)

    st.session_state["current_session_id"] = session["session_id"]
    st.session_state["tasks"] = tasks
    st.session_state["current_task_index"] = current_index
    st.session_state["last_feedback"] = ""
    st.session_state["last_verdict"] = ""
    st.session_state["user_answer"] = ""

