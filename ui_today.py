from datetime import date
from typing import Any

import streamlit as st

from gemini_service import generate_tasks, get_feedback_json
from scheduler import get_next_repetition, get_today_repetitions
from sheets import (
    create_session,
    find_session,
    get_latest_answer_for_task,
    get_session_progress,
    get_task_feedback_context,
    get_tasks_for_session,
    now_iso,
    save_answer,
    save_generated_tasks,
    save_mistake,
    save_task_feedback,
    skip_task,
    mark_bad_task,
    update_session_status,
    update_task_status,
)
from ui_common import (
    reset_session,
    render_task,
    load_session_into_state,
)


def render_today_tab(topics: list[dict[str, Any]], today_value: date) -> None:
    st.header("Сегодня")

    today_repetitions = get_today_repetitions(topics, today_value)

    if not today_repetitions:
        st.info("На выбранную дату нет тем для повторения.")

        with st.expander("Показать все активные темы"):
            for topic in topics:
                if topic.get("status") != "active":
                    continue

                st.write(
                    f"**Блок {topic['block']}. {topic['title']}** — "
                    f"изучено {topic.get('learned_date')}; "
                    f"следующее: {get_next_repetition(topic, today_value)}"
                )

        return

    options = {
        f"Блок {item['topic']['block']}. {item['topic']['title']} — день {item['repetition_day']}": item
        for item in today_repetitions
    }

    selected_label = st.selectbox("Выбери повторение", list(options.keys()))
    selected_item = options[selected_label]
    selected_topic = selected_item["topic"]
    selected_repetition_day = selected_item["repetition_day"]
    scheduled_date = today_value.isoformat()

    st.markdown(
        f"""
**Тема:** {selected_topic["stage"]}, блок {selected_topic["block"]}: {selected_topic["title"]}  
**Дата изучения:** {selected_topic.get("learned_date")}  
**День повторения:** {selected_repetition_day}
"""
    )

    session_matches_selection = (
        st.session_state.get("selected_topic_id") == selected_topic["id"]
        and st.session_state.get("selected_repetition_day") == selected_repetition_day
    )

    if not session_matches_selection:
        reset_session()
        st.session_state["selected_topic_id"] = selected_topic["id"]
        st.session_state["selected_repetition_day"] = selected_repetition_day

    existing_session = find_session(
        selected_topic["id"],
        selected_repetition_day,
        scheduled_date,
    )

    if existing_session and not st.session_state.get("tasks"):
        existing_tasks = get_tasks_for_session(existing_session["session_id"])
        answered_count = len([
            task for task in existing_tasks
            if task.get("status") == "answered"
        ])

        st.success(
            f"Для этой темы и даты уже есть сохранённая сессия: "
            f"{answered_count}/{len(existing_tasks)} задач решено."
        )

        if st.button("Продолжить сохранённую сессию"):
            load_session_into_state(existing_session)
            st.rerun()

    if not existing_session and not st.session_state.get("tasks"):
        if st.button("Начать сессию и сгенерировать задачи"):
            with st.spinner("Gemini генерирует 40 задач и сохраняет их в Google Sheets..."):
                try:
                    task_feedback_context = get_task_feedback_context(selected_topic["id"])
                    generated_tasks = generate_tasks(
                        selected_topic,
                        selected_repetition_day,
                        task_feedback_context=task_feedback_context,
                    )

                    session_id = create_session(
                        selected_topic["id"],
                        selected_repetition_day,
                        scheduled_date,
                    )

                    save_generated_tasks(
                        session_id,
                        selected_topic,
                        selected_repetition_day,
                        generated_tasks,
                    )

                    session = find_session(
                        selected_topic["id"],
                        selected_repetition_day,
                        scheduled_date,
                    )

                    if session is None:
                        raise RuntimeError("Сессия создана, но не найдена при повторном чтении.")

                    load_session_into_state(session)
                    st.success("Сессия и задачи сохранены в Google Sheets.")
                    st.rerun()
                except Exception as e:
                    st.error("Не удалось сгенерировать или сохранить задачи.")
                    st.code(str(e))

        return

    if not st.session_state.get("tasks"):
        return

    render_active_session(selected_topic, existing_session)


def render_active_session(
    selected_topic: dict[str, Any],
    existing_session: dict[str, Any] | None,
) -> None:
    tasks = st.session_state["tasks"]
    current_task_index = st.session_state.get("current_task_index", 0)
    progress = get_session_progress(tasks)

    st.markdown("### Прогресс сессии")

    if progress["total"]:
        st.progress((progress["answered"] + progress["skipped"] + progress["bad_tasks"]) / progress["total"])

    st.caption(
        f"Решено: {progress['answered']} · "
        f"пропущено: {progress['skipped']} · "
        f"плохие задачи: {progress['bad_tasks']} · "
        f"осталось: {progress['remaining']} · "
        f"всего: {progress['total']}"
    )

    if current_task_index >= len(tasks):
        st.success("Сессия завершена. Все задачи просмотрены.")

        if existing_session and progress["remaining"] == 0:
            try:
                update_session_status(existing_session, "completed", now_iso())
            except Exception:
                pass

        if st.button("Начать заново с первой задачи"):
            st.session_state["current_task_index"] = 0
            st.session_state["last_feedback"] = ""
            st.session_state["last_verdict"] = ""
            st.session_state["user_answer"] = ""
            st.rerun()

        st.stop()

    current_task = tasks[current_task_index]
    latest_answer = get_latest_answer_for_task(current_task["task_id"])

    render_task(current_task, current_task_index, len(tasks))

    if current_task.get("status") == "answered":
        st.info("Эта задача уже решена. Повторная отправка отключена.")
    elif current_task.get("status") == "skipped":
        st.warning("Эта задача была пропущена. Можно вернуться к ней позже.")
    elif current_task.get("status") == "bad_task":
        st.warning("Эта задача помечена как проблемная и не считается учебной ошибкой.")

    if latest_answer:
        with st.expander("Показать сохранённый ответ и фидбек", expanded=True):
            st.markdown("**Твой сохранённый ответ:**")
            st.code(latest_answer["user_answer"], language="python")
            st.markdown("**Фидбек Gemini:**")
            st.caption(f"Вердикт: {latest_answer.get('verdict', 'unknown')}")
            st.markdown(latest_answer["gemini_feedback"])

    answer_key = f"answer_input_{current_task['task_id']}"

    if answer_key not in st.session_state:
        st.session_state[answer_key] = ""

    user_answer = st.text_area(
        "Твой ответ",
        height=260,
        key=answer_key,
        disabled=current_task.get("status") in ["answered", "bad_task"],
    )

    col_prev, col_check, col_skip, col_next = st.columns(4)

    with col_prev:
        if st.button("← Назад", disabled=current_task_index == 0):
            st.session_state["current_task_index"] = max(0, current_task_index - 1)
            st.session_state["last_feedback"] = ""
            st.session_state["last_verdict"] = ""
            st.session_state["user_answer"] = ""
            st.rerun()

    with col_check:
        if st.button(
            "Проверить",
            disabled=current_task.get("status") in ["answered", "bad_task"],
        ):
            if not user_answer.strip():
                st.warning("Сначала напиши ответ.")
            else:
                handle_check_answer(current_task, selected_topic, user_answer)

    with col_skip:
        if st.button(
            "Пропустить",
            disabled=current_task.get("status") in ["answered", "bad_task"],
        ):
            try:
                skip_task(current_task)
                refreshed_tasks = get_tasks_for_session(current_task["session_id"])
                st.session_state["tasks"] = refreshed_tasks
                st.session_state["current_task_index"] = min(
                    current_task_index + 1,
                    len(refreshed_tasks),
                )
                st.session_state["last_feedback"] = ""
                st.session_state["last_verdict"] = ""
                st.session_state["user_answer"] = ""
                st.rerun()
            except Exception as e:
                st.error("Не удалось пропустить задачу.")
                st.code(str(e))

    with col_next:
        if st.button("Дальше →"):
            st.session_state["current_task_index"] = current_task_index + 1
            st.session_state["last_feedback"] = ""
            st.session_state["last_verdict"] = ""
            st.session_state["user_answer"] = ""
            st.rerun()

    render_task_complaint(current_task, current_task_index)

    if st.session_state.get("last_feedback"):
        st.markdown("### Фидбек Gemini")
        st.caption(f"Вердикт: {st.session_state.get('last_verdict', 'unknown')}")
        st.markdown(st.session_state["last_feedback"])


def handle_check_answer(
    current_task: dict[str, Any],
    selected_topic: dict[str, Any],
    user_answer: str,
) -> None:
    with st.spinner("Gemini проверяет ответ и сохраняет фидбек..."):
        try:
            feedback_data = get_feedback_json(
                current_task,
                user_answer,
                selected_topic,
            )

            save_answer(
                current_task,
                user_answer,
                feedback_data["feedback"],
                feedback_data["verdict"],
            )

            update_task_status(current_task, "answered")

            if feedback_data["verdict"] != "correct":
                save_mistake(
                    selected_topic,
                    current_task,
                    feedback_data["mistake_type"],
                    feedback_data["mistake_summary"],
                )

            st.session_state["last_feedback"] = feedback_data["feedback"]
            st.session_state["last_verdict"] = feedback_data["verdict"]
            st.session_state["user_answer"] = user_answer

            refreshed_tasks = get_tasks_for_session(current_task["session_id"])
            st.session_state["tasks"] = refreshed_tasks

            st.success("Ответ, фидбек и статус задачи сохранены.")
            st.rerun()
        except Exception as e:
            st.error("Не удалось получить или сохранить фидбек.")
            st.code(str(e))


def render_task_complaint(current_task: dict[str, Any], current_task_index: int) -> None:
    with st.expander("Пожаловаться на задачу / пометить как плохую"):
        issue_type = st.selectbox(
            "Что не так с задачей?",
            [
                "условие противоречит коду",
                "непонятно, что нужно сделать",
                "задача не по текущей теме",
                "слишком легко",
                "слишком сложно",
                "есть подсказка в условии",
                "другое",
            ],
        )

        issue_comment = st.text_area(
            "Комментарий",
            placeholder="Например: условие говорит, что код неправильный, но код уже корректный.",
            height=120,
            key=f"task_feedback_comment_{current_task['task_id']}",
        )

        if st.button(
            "Сохранить жалобу и убрать задачу из сессии",
            disabled=current_task.get("status") == "bad_task",
        ):
            try:
                save_task_feedback(current_task, issue_type, issue_comment)
                mark_bad_task(current_task)

                refreshed_tasks = get_tasks_for_session(current_task["session_id"])
                st.session_state["tasks"] = refreshed_tasks
                st.session_state["current_task_index"] = min(
                    current_task_index + 1,
                    len(refreshed_tasks),
                )
                st.session_state["last_feedback"] = ""
                st.session_state["last_verdict"] = ""
                st.session_state["user_answer"] = ""

                st.success("Задача помечена как проблемная и убрана из активного прохождения.")
                st.rerun()
            except Exception as e:
                st.error("Не удалось сохранить жалобу на задачу.")
                st.code(str(e))

