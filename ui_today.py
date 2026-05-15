from datetime import date
from typing import Any

import streamlit as st

from gemini_service import generate_tasks, get_feedback_json, get_task_hint
from scheduler import get_due_repetitions, get_next_repetition
from sheets import (
    create_session,
    find_session,
    get_latest_answer_for_task,
    get_session_progress,
    get_task_feedback_context,
    get_tasks_for_session,
    load_sessions,
    now_iso,
    save_answer,
    save_generated_tasks,
    save_mistake,
    save_task_feedback,
    skip_task,
    mark_bad_task,
    task_status_from_verdict,
    update_session_status,
    update_task_status,
    validate_generated_tasks,
    get_topic_materials_context,
    load_topic_materials,
    save_topic_material,
)
from ui_common import (
    reset_session,
    render_task,
    load_session_into_state,
)
from ui_datasets import get_dataset_selector


def render_today_tab(topics: list[dict[str, Any]], today_value: date) -> None:
    st.header("Сегодня")

    try:
        sessions = load_sessions()
    except Exception:
        sessions = []

    due_repetitions = get_due_repetitions(topics, today_value, sessions=sessions)

    if not due_repetitions:
        st.info("На выбранную дату нет тем для повторения и просроченных повторений.")

        with st.expander("Показать все активные темы"):
            for topic in topics:
                if topic.get("status") not in ["active", "learned"]:
                    continue

                st.write(
                    f"**Блок {topic['block']}. {topic['title']}** — "
                    f"изучено {topic.get('learned_date')}; "
                    f"следующее: {get_next_repetition(topic, today_value)}"
                )

        return

    overdue_count = len([item for item in due_repetitions if item.get("is_overdue")])
    if overdue_count:
        st.warning(f"Есть просроченные повторения: {overdue_count}. Они остаются в списке, пока сессия не завершена.")

    options = {}
    for item in due_repetitions:
        topic = item["topic"]
        if item.get("is_overdue"):
            label = (
                f"Просрочено на {item['days_overdue']} дн. — "
                f"Блок {topic['block']}. {topic['title']} — "
                f"день {item['repetition_day']} ({item['scheduled_date'].isoformat()})"
            )
        else:
            label = (
                f"Сегодня — Блок {topic['block']}. {topic['title']} — "
                f"день {item['repetition_day']}"
            )
        options[label] = item

    selected_label = st.selectbox("Выбери повторение", list(options.keys()))
    selected_item = options[selected_label]
    selected_topic = selected_item["topic"]
    selected_repetition_day = selected_item["repetition_day"]
    scheduled_date = selected_item["scheduled_date"].isoformat()

    st.markdown(
        f"""
**Тема:** {selected_topic["stage"]}, блок {selected_topic["block"]}: {selected_topic["title"]}  
**Дата изучения:** {selected_topic.get("learned_date")}  
**День повторения:** {selected_repetition_day}  
**Плановая дата повторения:** {scheduled_date}
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
            if task.get("status") in ["answered", "correct", "partially_correct", "incorrect"]
        ])

        st.success(
            f"Для этой темы и даты уже есть сохранённая сессия: "
            f"{answered_count}/{len(existing_tasks)} задач решено."
        )

        if st.button("Продолжить сохранённую сессию"):
            st.session_state["active_session_source"] = "today"
            load_session_into_state(existing_session)
            st.rerun()

    if not existing_session and not st.session_state.get("tasks"):
        selected_dataset = get_dataset_selector(
            label="Датасет для генерации задач",
            key=f"today_dataset_{selected_topic['id']}_{selected_repetition_day}_{scheduled_date}",
        )

        difficulty_profile = st.selectbox(
            "Режим генерации задач",
            options=["balanced", "harder", "interview"],
            format_func=lambda value: {
                "balanced": "Сбалансированный",
                "harder": "Сложнее обычного",
                "interview": "Ближе к тестам для аналитика",
            }.get(value, value),
            help=(
                "Сложные режимы всё равно должны оставаться в рамках текущей и уже изученных тем, "
                "но задачи будут менее однотипными."
            ),
            key=f"difficulty_profile_{selected_topic['id']}_{selected_repetition_day}_{scheduled_date}",
        )

        try:
            saved_materials = [
                item for item in load_topic_materials()
                if item.get("topic_id") == selected_topic["id"] and item.get("status") == "active"
            ]
        except Exception:
            saved_materials = []

        with st.expander(f"Материалы по теме для генерации задач ({len(saved_materials)} сохранено)"):
            if saved_materials:
                st.caption("Эти материалы будут учитываться при генерации задач.")
                for item in saved_materials[-5:]:
                    st.write(f"- {item.get('title') or 'Материал без названия'}")
            else:
                st.caption("Сохранённых материалов по этой теме пока нет.")

            material_title = st.text_input(
                "Название материала",
                value="Конспект / диалог по теме",
                key=f"material_title_{selected_topic['id']}_{selected_repetition_day}_{scheduled_date}",
            )
            extra_materials = st.text_area(
                "Дополнительный материал для этой генерации",
                placeholder=(
                    "Можно вставить сюда конспект, кусок диалога с ИИ, типы задач, объяснения "
                    "или примеры, по которым ты учился."
                ),
                height=180,
                key=f"extra_materials_{selected_topic['id']}_{selected_repetition_day}_{scheduled_date}",
            )
            save_material = st.checkbox(
                "Сохранить этот материал для будущих генераций по теме",
                value=False,
                key=f"save_material_{selected_topic['id']}_{selected_repetition_day}_{scheduled_date}",
            )

        if st.button("Начать сессию и сгенерировать задачи"):
            with st.spinner("Gemini генерирует 40 задач и сохраняет их в Google Sheets..."):
                try:
                    task_feedback_context = get_task_feedback_context(selected_topic["id"])

                    if save_material and extra_materials.strip():
                        save_topic_material(
                            selected_topic["id"],
                            material_title,
                            extra_materials,
                        )

                    topic_materials_context = get_topic_materials_context(
                        selected_topic["id"],
                        extra_materials=extra_materials,
                    )

                    generated_tasks = generate_tasks(
                        selected_topic,
                        selected_repetition_day,
                        task_feedback_context=task_feedback_context,
                        dataset=selected_dataset,
                        difficulty_profile=difficulty_profile,
                        topic_materials_context=topic_materials_context,
                    )
                    generated_tasks = validate_generated_tasks(generated_tasks, expected_total=40)

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

                    st.session_state["active_session_source"] = "today"
                    load_session_into_state(session)
                    st.success("Сессия и задачи сохранены в Google Sheets.")
                    st.rerun()
                except Exception as e:
                    st.error("Не удалось сгенерировать или сохранить задачи.")
                    st.code(str(e))

        return

    if not st.session_state.get("tasks"):
        return

    if st.session_state.get("active_session_source") not in [None, "today"]:
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
        st.progress(progress["completed"] / progress["total"])

    st.caption(
        f"Ответов: {progress['answered']} · "
        f"верно: {progress['correct']} · "
        f"требуют повтора: {progress['partially_correct'] + progress['incorrect']} · "
        f"пропущено: {progress['skipped']} · "
        f"плохие задачи: {progress['bad_tasks']} · "
        f"осталось: {progress['remaining']} · "
        f"всего: {progress['total']}"
    )

    if current_task_index >= len(tasks):
        if progress["remaining"] == 0:
            st.success("Сессия завершена. Все задачи закрыты.")

            if existing_session:
                try:
                    update_session_status(existing_session, "completed", now_iso())
                except Exception:
                    pass
        else:
            st.warning(
                "Все задачи просмотрены, но часть ответов ещё не зачтена. "
                "Вернись к первой задаче, которая требует повтора."
            )

        col_restart, col_retry, col_exit = st.columns(3)

        with col_restart:
            if st.button("Начать заново с первой задачи"):
                st.session_state["current_task_index"] = 0
                st.session_state["last_feedback"] = ""
                st.session_state["last_verdict"] = ""
                st.session_state["user_answer"] = ""
                st.rerun()

        with col_retry:
            if st.button("К первой незачтённой задаче", disabled=progress["remaining"] == 0):
                for index, task in enumerate(tasks):
                    if task.get("status") not in ["answered", "correct", "skipped", "bad_task"]:
                        st.session_state["current_task_index"] = index
                        st.session_state["last_feedback"] = ""
                        st.session_state["last_verdict"] = ""
                        st.session_state["user_answer"] = ""
                        st.rerun()

        with col_exit:
            if st.button("Закрыть сессию и вернуться к списку"):
                reset_session()
                st.rerun()

        st.stop()

    current_task = tasks[current_task_index]
    latest_answer = get_latest_answer_for_task(current_task["task_id"])

    render_task(current_task, current_task_index, len(tasks))

    current_status = current_task.get("status")

    if current_status in ["answered", "correct"]:
        st.success("Эта задача уже зачтена. Повторная отправка отключена.")
    elif current_status in ["incorrect", "partially_correct"]:
        st.warning("Ответ сохранён, но задача ещё не зачтена. Можно исправить ответ и отправить ещё раз.")
    elif current_status == "skipped":
        st.warning("Эта задача была пропущена. Её можно решить позже.")
    elif current_status == "bad_task":
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
        disabled=current_task.get("status") in ["answered", "correct", "bad_task"],
    )

    col_prev, col_check, col_hint, col_skip, col_next = st.columns(5)

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
            disabled=current_task.get("status") in ["answered", "correct", "bad_task"],
        ):
            if not user_answer.strip():
                st.warning("Сначала напиши ответ.")
            else:
                handle_check_answer(current_task, selected_topic, user_answer)

    with col_hint:
        hint_mode = st.selectbox(
            "Помощь",
            options=["hint", "consultation"],
            format_func=lambda value: "Подсказка" if value == "hint" else "Консультация",
            label_visibility="collapsed",
            key=f"hint_mode_{current_task['task_id']}",
        )
        if st.button("Помощь", key=f"hint_button_{current_task['task_id']}"):
            with st.spinner("Gemini готовит подсказку..."):
                try:
                    st.session_state[f"hint_text_{current_task['task_id']}"] = get_task_hint(
                        current_task,
                        selected_topic,
                        user_answer=user_answer,
                        hint_mode=hint_mode,
                    )
                except Exception as e:
                    st.error("Не удалось получить подсказку.")
                    st.code(str(e))

    with col_skip:
        if st.button(
            "Пропустить",
            disabled=current_task.get("status") in ["answered", "correct", "bad_task"],
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

    hint_text = st.session_state.get(f"hint_text_{current_task['task_id']}")
    if hint_text:
        with st.expander("Подсказка / консультация", expanded=True):
            st.markdown(hint_text)

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

            normalized_status = task_status_from_verdict(feedback_data["verdict"])
            update_task_status(current_task, normalized_status)

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

