from datetime import date
from typing import Any

import streamlit as st

from gemini_service import FALLBACK_MODELS, generate_tasks, get_feedback_json
from scheduler import (
    REPETITION_DAYS,
    get_next_repetition,
    get_today_repetitions,
    get_upcoming_repetitions,
    parse_date,
)
from sheets import (
    build_progress_stats,
    create_session,
    find_session,
    get_first_unanswered_index,
    get_latest_answer_for_task,
    get_session_progress,
    get_task_feedback_context,
    get_tasks_for_session,
    get_top_mistakes,
    load_answers,
    load_mistakes,
    load_sessions,
    load_tasks,
    mark_bad_task,
    now_iso,
    save_answer,
    save_generated_tasks,
    save_mistake,
    save_task_feedback,
    skip_task,
    update_session_status,
    update_task_status,
    update_topic,
)


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


def render_plan_tab(topics: list[dict[str, Any]], today_value: date) -> None:
    st.header("Учебный план")

    st.info(
        "Темы, статусы и даты читаются из Google Sheets. "
        "Изменения сохраняются обратно в лист topics."
    )

    selected_topic_for_edit = st.selectbox(
        "Тема",
        topics,
        format_func=lambda topic: f"Блок {topic['block']}. {topic['title']}",
    )

    current_status = selected_topic_for_edit.get("status", "planned")
    if current_status not in ["planned", "active", "completed", "paused"]:
        current_status = "planned"

    current_learned_date = selected_topic_for_edit.get("learned_date", "")

    status = st.selectbox(
        "Статус",
        ["planned", "active", "paused", "completed"],
        index=["planned", "active", "paused", "completed"].index(current_status),
        format_func=lambda value: {
            "planned": "запланирована",
            "active": "пройдена, повторять",
            "paused": "на паузе",
            "completed": "закрыта",
        }[value],
    )

    default_date = (
        parse_date(current_learned_date)
        if current_learned_date
        else today_value
    )

    learned_date_input = st.date_input(
        "Дата изучения темы",
        value=default_date,
    )

    col_a, col_b = st.columns(2)

    with col_a:
        if st.button("Сохранить дату и статус"):
            try:
                update_topic(
                    selected_topic_for_edit,
                    learned_date_input.isoformat(),
                    status,
                )
                reset_session()
                st.success("Сохранено в Google Sheets.")
                st.rerun()
            except Exception as e:
                st.error("Не удалось сохранить изменения.")
                st.code(str(e))

    with col_b:
        if st.button("Отметить как пройденную сегодня"):
            try:
                update_topic(
                    selected_topic_for_edit,
                    today_value.isoformat(),
                    "active",
                )
                reset_session()
                st.success("Тема отмечена как пройденная сегодня.")
                st.rerun()
            except Exception as e:
                st.error("Не удалось сохранить изменения.")
                st.code(str(e))

    st.subheader("Все темы")

    for topic in topics:
        st.write(
            f"**Блок {topic['block']}. {topic['title']}** — "
            f"статус: `{topic.get('status')}`, "
            f"дата изучения: `{topic.get('learned_date') or 'не указана'}`, "
            f"следующее: {get_next_repetition(topic, today_value)}"
        )


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


def render_progress_tab(topics: list[dict[str, Any]], today_value: date) -> None:
    st.header("Прогресс")

    try:
        sessions = load_sessions()
        tasks = load_tasks()
        answers = load_answers()
        mistakes = load_mistakes()
        stats = build_progress_stats(topics, sessions, tasks, answers)

        col1, col2, col3, col4 = st.columns(4)
        col1.metric("Сессий", stats["sessions_count"])
        col2.metric("Задач решено", f"{stats['answered_tasks']}/{stats['total_tasks']}")
        col3.metric("Ответов сохранено", stats["answers_count"])
        col4.metric("Плохих задач", stats.get("bad_tasks_count", 0))

        verdict_counts = stats["verdict_counts"]

        st.subheader("Качество ответов")
        col_a, col_b, col_c, col_d = st.columns(4)
        col_a.metric("Корректно", verdict_counts["correct"])
        col_b.metric("Частично", verdict_counts["partially_correct"])
        col_c.metric("Некорректно", verdict_counts["incorrect"])
        col_d.metric("Неясно", verdict_counts["unknown"])

        if stats["answered_tasks"] > 0:
            correct_rate = round(verdict_counts["correct"] / stats["answered_tasks"] * 100)
            st.progress(correct_rate / 100)
            st.caption(f"Доля корректных ответов: {correct_rate}%")

        st.subheader("Ближайшие повторения на 7 дней")
        upcoming = get_upcoming_repetitions(topics, today_value, horizon_days=7)

        if not upcoming:
            st.info("На ближайшие 7 дней повторений нет.")
        else:
            for item in upcoming:
                st.write(
                    f"**{item['date'].isoformat()}** — "
                    f"Блок {item['topic']['block']}. {item['topic']['title']} — "
                    f"день {item['repetition_day']}"
                )

        st.subheader("Топ ошибок")
        top_mistakes = get_top_mistakes(mistakes)

        if not top_mistakes:
            st.info("Ошибок пока нет.")
        else:
            for mistake_type, count in top_mistakes:
                st.write(f"**{mistake_type}** — {count}")

        st.subheader("По темам")

        for topic_stat in stats["topic_stats"].values():
            total = topic_stat["total"]
            answered = topic_stat["answered"]
            ratio = answered / total if total else 0

            st.write(
                f"**{topic_stat['title']}** — "
                f"решено {answered}/{total}; "
                f"корректно: {topic_stat['correct']}, "
                f"частично: {topic_stat['partial']}, "
                f"ошибки: {topic_stat['incorrect']}, "
                f"плохие задачи: {topic_stat.get('bad_tasks', 0)}"
            )
            st.progress(ratio)

    except Exception as e:
        st.error("Не удалось построить прогресс.")
        st.code(str(e))


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

        st.stop()

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

        st.stop()

    if not st.session_state.get("tasks"):
        st.stop()

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
