from datetime import date, timedelta

import streamlit as st

from scheduler import parse_date
from sheets import update_topic
from ui_common import reset_session


def format_topic_option(topic: dict) -> str:
    stage = topic.get("stage", "")
    block = topic.get("block", "")
    title = topic.get("title", "")

    if stage:
        return f"{stage} · Блок {block}. {title}"

    return f"Блок {block}. {title}"


def get_stage_sort_key(stage: str) -> tuple[int, str]:
    try:
        number = int(str(stage).replace("Этап", "").strip())
        return (number, stage)
    except Exception:
        return (999, stage)


def render_plan_tab(topics: list[dict], today_value: date) -> None:
    st.header("Учебный план")

    st.info(
        "Темы, статусы и даты читаются из Google Sheets. "
        "Изменения сохраняются обратно в лист topics."
    )

    if not topics:
        st.warning("В учебном плане пока нет тем.")
        return

    stages = sorted(
        {
            topic.get("stage", "Без этапа")
            for topic in topics
        },
        key=get_stage_sort_key,
    )

    selected_stage = st.selectbox(
        "Этап обучения",
        ["Все этапы"] + stages,
        key="plan_selected_stage",
    )

    visible_topics = topics

    if selected_stage != "Все этапы":
        visible_topics = [
            topic for topic in topics
            if topic.get("stage", "Без этапа") == selected_stage
        ]

    if not visible_topics:
        st.warning("Для выбранного этапа нет тем.")
        return

    topic = st.selectbox(
        "Тема",
        visible_topics,
        format_func=format_topic_option,
        key="plan_selected_topic",
    )

    st.markdown("### Карточка темы")

    col1, col2 = st.columns(2)

    with col1:
        st.write(f"**Этап:** {topic.get('stage', '')}")
        st.write(f"**Блок:** {topic.get('block', '')}")
        st.write(f"**Тема:** {topic.get('title', '')}")

    with col2:
        st.write(f"**Статус:** `{topic.get('status', '')}`")
        learned_date = topic.get("learned_date") or "не указана"
        st.write(f"**Дата изучения:** {learned_date}")
        known_blocks = topic.get("known_blocks", [])
        known_blocks_text = ", ".join(str(block) for block in known_blocks) or "не указаны"
        st.write(f"**Известные блоки:** {known_blocks_text}")

    description = topic.get("description", "")

    if description:
        with st.expander("Описание темы", expanded=True):
            st.write(description)

    status_options = ["planned", "learned", "archived"]
    current_status = topic.get("status", "planned")

    if current_status not in status_options:
        status_options.append(current_status)

    status_label_map = {
        "planned": "запланирована",
        "learned": "изучена",
        "archived": "архив",
    }

    status = st.selectbox(
        "Статус",
        status_options,
        index=status_options.index(current_status),
        format_func=lambda value: status_label_map.get(value, value),
        key=f"status_{topic['id']}",
    )

    learned_date_input = st.text_input(
        "Дата изучения темы",
        value=topic.get("learned_date") or today_value.strftime("%Y-%m-%d"),
        key=f"learned_date_{topic['id']}",
    )

    col_save, col_today, col_clear = st.columns(3)

    with col_save:
        if st.button("Сохранить изменения", key=f"save_topic_{topic['id']}"):
            try:
                update_topic(
                    topic,
                    learned_date_input,
                    status,
                )
                reset_session()
                st.cache_data.clear()
                st.success("Тема обновлена.")
                st.rerun()
            except Exception as e:
                st.error("Не удалось обновить тему.")
                st.code(str(e))

    with col_today:
        if st.button("Отметить изученной сегодня", key=f"learned_today_{topic['id']}"):
            try:
                update_topic(
                    topic,
                    today_value.strftime("%Y-%m-%d"),
                    "learned",
                )
                reset_session()
                st.cache_data.clear()
                st.success("Тема отмечена как изученная сегодня.")
                st.rerun()
            except Exception as e:
                st.error("Не удалось обновить тему.")
                st.code(str(e))

    with col_clear:
        if st.button("Снять дату", key=f"clear_date_{topic['id']}"):
            try:
                update_topic(
                    topic,
                    "",
                    status,
                )
                reset_session()
                st.cache_data.clear()
                st.success("Дата изучения очищена.")
                st.rerun()
            except Exception as e:
                st.error("Не удалось очистить дату.")
                st.code(str(e))

    st.markdown("---")

    st.subheader("Ближайшие повторения по выбранной теме")

    parsed_learned_date = parse_date(topic.get("learned_date"))

    if not parsed_learned_date:
        st.info("У темы пока нет даты изучения. Повторения не рассчитываются.")
        return

    upcoming = []

    for repetition_day in [1, 3, 7, 14, 30]:
        repetition_date = parsed_learned_date + timedelta(days=repetition_day)

        upcoming.append(
            {
                "День": repetition_day,
                "Дата": repetition_date.strftime("%Y-%m-%d"),
                "Статус": (
                    "сегодня"
                    if repetition_date == today_value
                    else "прошло"
                    if repetition_date < today_value
                    else "впереди"
                ),
            }
        )

    st.table(upcoming)
