from datetime import date

import streamlit as st

from scheduler import get_next_repetition, parse_date
from sheets import update_topic
from ui_common import reset_session


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

