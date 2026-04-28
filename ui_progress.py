from datetime import date

import streamlit as st

from scheduler import get_upcoming_repetitions
from sheets import (
    build_progress_stats,
    get_top_mistakes,
    load_answers,
    load_mistakes,
    load_sessions,
    load_tasks,
)


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

