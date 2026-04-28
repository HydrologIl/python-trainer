from datetime import date
from typing import Any

import streamlit as st

from gemini_service import generate_weak_spot_tasks
from sheets import (
    create_session,
    load_mistakes,
    now_iso,
    save_generated_tasks,
)
from ui_common import load_session_into_state
from ui_today import render_active_session
from ui_datasets import get_dataset_selector


def group_mistakes_by_topic_and_type(
    mistakes: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    grouped: dict[tuple[str, str], dict[str, Any]] = {}

    for mistake in mistakes:
        topic_id = mistake.get("topic_id", "")
        mistake_type = mistake.get("mistake_type", "") or "unknown"
        key = (topic_id, mistake_type)

        if key not in grouped:
            grouped[key] = {
                "topic_id": topic_id,
                "mistake_type": mistake_type,
                "count": 0,
                "examples": [],
            }

        grouped[key]["count"] += 1

        summary = mistake.get("mistake_summary", "")
        if summary and len(grouped[key]["examples"]) < 5:
            grouped[key]["examples"].append(summary)

    return sorted(
        grouped.values(),
        key=lambda item: item["count"],
        reverse=True,
    )


def render_weak_spots_tab(topics: list[dict[str, Any]], today_value: date) -> None:
    st.header("Слабые места")

    st.write(
        "Здесь можно взять частую ошибку из истории и сгенерировать короткую "
        "дополнительную тренировку. Это не заменяет расписание по Эббингаузу."
    )

    try:
        mistakes = load_mistakes()
    except Exception as e:
        st.error("Не удалось прочитать лист mistakes.")
        st.code(str(e))
        return

    if not mistakes:
        st.info("Ошибок пока нет. Режим появится, когда накопится хотя бы одна ошибка.")
        return

    grouped_mistakes = group_mistakes_by_topic_and_type(mistakes)
    topic_by_id = {topic["id"]: topic for topic in topics}

    options = []

    for item in grouped_mistakes:
        topic = topic_by_id.get(item["topic_id"])
        if not topic:
            continue

        label = (
            f"Блок {topic['block']}. {topic['title']} — "
            f"{item['mistake_type']} — {item['count']} раз"
        )

        options.append((label, item, topic))

    if not options:
        st.info("Ошибки есть, но они не сопоставились с темами из учебного плана.")
        return

    selected_label = st.selectbox(
        "Выбери слабое место",
        [option[0] for option in options],
    )

    selected_item = next(option for option in options if option[0] == selected_label)
    _, mistake_group, selected_topic = selected_item

    st.markdown(
        f"""
**Тема:** {selected_topic["stage"]}, блок {selected_topic["block"]}: {selected_topic["title"]}  
**Тип ошибки:** `{mistake_group["mistake_type"]}`  
**Количество:** {mistake_group["count"]}
"""
    )

    if mistake_group["examples"]:
        with st.expander("Примеры ошибок из истории"):
            for example in mistake_group["examples"]:
                st.write(f"- {example}")

    task_count = st.slider(
        "Сколько задач сгенерировать",
        min_value=5,
        max_value=20,
        value=10,
        step=5,
    )

    difficulty = st.selectbox(
        "Сложность",
        ["начальный", "средний", "продвинутый"],
        index=0,
    )

    selected_dataset = get_dataset_selector(
        label="Датасет для тренировки слабого места",
        key=f"weak_dataset_{selected_topic['id']}_{mistake_group['mistake_type']}",
    )

    if st.button("Сгенерировать тренировку на слабое место"):
        with st.spinner("Gemini генерирует тренировку и сохраняет её в Google Sheets..."):
            try:
                generated_tasks = generate_weak_spot_tasks(
                    topic=selected_topic,
                    mistake_type=mistake_group["mistake_type"],
                    mistake_examples=mistake_group["examples"],
                    task_count=task_count,
                    difficulty=difficulty,
                    dataset=selected_dataset,
                )

                session_id = create_session(
                    selected_topic["id"],
                    -1,
                    today_value.isoformat(),
                )

                save_generated_tasks(
                    session_id,
                    selected_topic,
                    -1,
                    generated_tasks,
                )

                session = {
                    "session_id": session_id,
                    "topic_id": selected_topic["id"],
                    "repetition_day": -1,
                    "scheduled_date": today_value.isoformat(),
                    "started_at": now_iso(),
                    "completed_at": "",
                    "status": "in_progress",
                }

                st.session_state["selected_topic_id"] = selected_topic["id"]
                st.session_state["selected_repetition_day"] = -1
                st.session_state["active_session_source"] = "weak_spots"
                load_session_into_state(session)

                st.success("Тренировка сохранена. Можно решать прямо здесь.")
                st.rerun()
            except Exception as e:
                st.error("Не удалось сгенерировать тренировку на слабое место.")
                st.code(str(e))

    if (
        st.session_state.get("tasks")
        and st.session_state.get("selected_topic_id") == selected_topic["id"]
        and st.session_state.get("selected_repetition_day") == -1
        and st.session_state.get("active_session_source") != "sessions"
    ):
        st.markdown("---")
        st.subheader("Текущая тренировка на слабое место")
        render_active_session(selected_topic, None)

