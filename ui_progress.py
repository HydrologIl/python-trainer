from collections import Counter, defaultdict
from datetime import date

import pandas as pd
import streamlit as st

from gemini_service import normalize_verdict
from scheduler import get_upcoming_repetitions
from sheets import (
    build_progress_stats,
    load_answers,
    load_mistakes,
    load_sessions,
    load_tasks,
)


def safe_int(value) -> int:
    try:
        return int(value)
    except Exception:
        return 0


def percent(part: int, total: int) -> float:
    if total == 0:
        return 0.0
    return round(part / total * 100, 1)


def render_overview_metrics(stats: dict) -> None:
    total_tasks = safe_int(stats.get("total_tasks", 0))
    answered_tasks = safe_int(stats.get("answered_tasks", 0))
    answers_count = safe_int(stats.get("answers_count", 0))
    attempts_count = safe_int(stats.get("attempts_count", answers_count))
    bad_tasks_count = safe_int(stats.get("bad_tasks_count", 0))

    verdict_counts = stats.get("verdict_counts", {})
    correct = safe_int(verdict_counts.get("correct", 0))
    partial = safe_int(verdict_counts.get("partially_correct", 0))
    incorrect = safe_int(verdict_counts.get("incorrect", 0))

    col1, col2, col3, col4 = st.columns(4)

    col1.metric("Решено задач", f"{answered_tasks}/{total_tasks}")
    col2.metric("Качество correct", f"{percent(correct, answers_count)}%")
    col3.metric("Ошибок", incorrect)
    col4.metric("Плохих задач", bad_tasks_count)

    col5, col6, col7, col8 = st.columns(4)
    col5.metric("Correct", correct)
    col6.metric("Partially correct", partial)
    col7.metric("Incorrect", incorrect)
    col8.metric("Проверок всего", attempts_count)


def build_topic_progress_table(stats: dict) -> pd.DataFrame:
    rows = []

    for topic_stat in stats.get("topic_stats", {}).values():
        total = safe_int(topic_stat.get("total", 0))
        answered = safe_int(topic_stat.get("answered", 0))
        correct = safe_int(topic_stat.get("correct", 0))
        partial = safe_int(topic_stat.get("partial", 0))
        incorrect = safe_int(topic_stat.get("incorrect", 0))
        bad_tasks = safe_int(topic_stat.get("bad_tasks", 0))
        attempts = safe_int(topic_stat.get("attempts", 0))

        checked = correct + partial + incorrect

        rows.append(
            {
                "Тема": topic_stat.get("title", ""),
                "Решено": answered,
                "Всего": total,
                "Прогресс, %": percent(answered, total),
                "Correct": correct,
                "Partial": partial,
                "Incorrect": incorrect,
                "Качество correct, %": percent(correct, checked),
                "Проверок": attempts,
                "Плохие задачи": bad_tasks,
            }
        )

    if not rows:
        return pd.DataFrame()

    df = pd.DataFrame(rows)
    return df.sort_values(["Прогресс, %", "Качество correct, %"], ascending=[True, True])


def build_active_sessions_table(
    sessions: list[dict],
    tasks: list[dict],
    topic_by_id: dict[str, dict],
) -> pd.DataFrame:
    tasks_by_session = defaultdict(list)

    for task in tasks:
        tasks_by_session[task.get("session_id")].append(task)

    rows = []

    for session in sessions:
        if session.get("status") == "completed":
            continue

        session_id = session.get("session_id")
        session_tasks = tasks_by_session.get(session_id, [])
        total = len(session_tasks)
        answered = len([
            task for task in session_tasks
            if task.get("status") in ["answered", "correct", "partially_correct", "incorrect"]
        ])
        correct = len([
            task for task in session_tasks
            if task.get("status") in ["answered", "correct"]
        ])
        needs_retry = len([
            task for task in session_tasks
            if task.get("status") in ["partially_correct", "incorrect"]
        ])
        skipped = len([
            task for task in session_tasks
            if task.get("status") == "skipped"
        ])
        bad = len([
            task for task in session_tasks
            if task.get("status") == "bad_task"
        ])

        topic = topic_by_id.get(session.get("topic_id"), {})
        repetition_day = session.get("repetition_day")
        repetition_label = (
            "слабое место"
            if repetition_day == -1
            else f"день {repetition_day}"
        )

        rows.append(
            {
                "Тема": topic.get("title", session.get("topic_id", "")),
                "Тип": repetition_label,
                "Дата": session.get("scheduled_date", ""),
                "Ответов": answered,
                "Зачтено": correct,
                "На повтор": needs_retry,
                "Всего": total,
                "Прогресс, %": percent(correct + skipped + bad, total),
                "Пропущено": skipped,
                "Плохие": bad,
                "Статус": session.get("status", ""),
            }
        )

    if not rows:
        return pd.DataFrame()

    return pd.DataFrame(rows).sort_values(["Дата", "Прогресс, %"])


def build_mistake_tables(
    mistakes: list[dict],
    topic_by_id: dict[str, dict],
) -> tuple[pd.DataFrame, pd.DataFrame]:
    type_counter = Counter()
    topic_type_counter = Counter()

    for mistake in mistakes:
        mistake_type = mistake.get("mistake_type") or "unknown"
        topic_id = mistake.get("topic_id")
        topic = topic_by_id.get(topic_id, {})
        topic_title = topic.get("title", topic_id or "unknown")

        type_counter[mistake_type] += 1
        topic_type_counter[(topic_title, mistake_type)] += 1

    type_rows = [
        {"Тип ошибки": mistake_type, "Количество": count}
        for mistake_type, count in type_counter.most_common()
    ]

    topic_rows = [
        {
            "Тема": topic_title,
            "Тип ошибки": mistake_type,
            "Количество": count,
        }
        for (topic_title, mistake_type), count in topic_type_counter.most_common()
    ]

    return pd.DataFrame(type_rows), pd.DataFrame(topic_rows)


def get_latest_answers_by_task(answers: list[dict]) -> dict[str, dict]:
    latest: dict[str, dict] = {}
    for answer in sorted(answers, key=lambda item: item.get("created_at", "")):
        latest[answer.get("task_id", "")] = answer
    return latest


def build_task_type_table(tasks: list[dict], answers: list[dict]) -> pd.DataFrame:
    latest_answers = get_latest_answers_by_task(answers)
    rows_by_type: dict[str, dict] = defaultdict(lambda: {
        "total": 0,
        "attempted": 0,
        "correct": 0,
        "partial": 0,
        "incorrect": 0,
        "bad": 0,
    })

    for task in tasks:
        task_type = task.get("type") or "unknown"
        row = rows_by_type[task_type]

        if task.get("status") == "bad_task":
            row["bad"] += 1
            continue

        row["total"] += 1
        latest_answer = latest_answers.get(task.get("task_id"))

        if not latest_answer:
            continue

        row["attempted"] += 1
        verdict = normalize_verdict(latest_answer.get("verdict", "unknown"))

        if verdict == "correct":
            row["correct"] += 1
        elif verdict == "partially_correct":
            row["partial"] += 1
        elif verdict == "incorrect":
            row["incorrect"] += 1

    rows = []
    for task_type, data in rows_by_type.items():
        checked = data["correct"] + data["partial"] + data["incorrect"]
        rows.append(
            {
                "Тип задач": task_type,
                "Всего": data["total"],
                "С попытками": data["attempted"],
                "Correct": data["correct"],
                "Partial": data["partial"],
                "Incorrect": data["incorrect"],
                "Качество correct, %": percent(data["correct"], checked),
                "Плохие задачи": data["bad"],
            }
        )

    if not rows:
        return pd.DataFrame()

    return pd.DataFrame(rows).sort_values("Качество correct, %", ascending=True)


def build_answer_trend_table(answers: list[dict]) -> pd.DataFrame:
    rows_by_date: dict[str, dict] = defaultdict(lambda: {
        "correct": 0,
        "partial": 0,
        "incorrect": 0,
        "total": 0,
    })

    for answer in answers:
        created_at = answer.get("created_at", "")
        day = created_at[:10] if len(created_at) >= 10 else "unknown"
        verdict = normalize_verdict(answer.get("verdict", "unknown"))
        row = rows_by_date[day]
        row["total"] += 1

        if verdict == "correct":
            row["correct"] += 1
        elif verdict == "partially_correct":
            row["partial"] += 1
        elif verdict == "incorrect":
            row["incorrect"] += 1

    rows = []
    for day, data in rows_by_date.items():
        rows.append(
            {
                "Дата": day,
                "Проверок": data["total"],
                "Correct": data["correct"],
                "Partial": data["partial"],
                "Incorrect": data["incorrect"],
                "Качество correct, %": percent(data["correct"], data["total"]),
            }
        )

    if not rows:
        return pd.DataFrame()

    return pd.DataFrame(rows).sort_values("Дата", ascending=False)


def build_upcoming_table(topics: list[dict], today_value: date) -> pd.DataFrame:
    upcoming = get_upcoming_repetitions(topics, today_value, days_ahead=14)

    rows = []

    for item in upcoming:
        topic = item["topic"]

        rows.append(
            {
                "Дата": item["date"].isoformat(),
                "Через дней": item["days_from_today"],
                "Тема": topic["title"],
                "Блок": topic["block"],
                "День повторения": item["repetition_day"],
            }
        )

    if not rows:
        return pd.DataFrame()

    return pd.DataFrame(rows).sort_values(["Дата", "День повторения"])


def render_progress_tab(topics: list[dict], today_value: date) -> None:
    st.header("Прогресс")

    try:
        sessions = load_sessions()
        tasks = load_tasks()
        answers = load_answers()
        mistakes = load_mistakes()

        stats = build_progress_stats(topics, sessions, tasks, answers)
        topic_by_id = {topic["id"]: topic for topic in topics}

        st.subheader("Общая сводка")
        render_overview_metrics(stats)

        st.markdown("---")

        st.subheader("Прогресс по темам")
        topic_df = build_topic_progress_table(stats)

        if topic_df.empty:
            st.info("Пока нет данных по задачам.")
        else:
            st.dataframe(
                topic_df,
                use_container_width=True,
                hide_index=True,
            )

        st.markdown("---")

        st.subheader("Качество по типам задач")
        task_type_df = build_task_type_table(tasks, answers)

        if task_type_df.empty:
            st.info("Пока нет данных по типам задач.")
        else:
            st.dataframe(
                task_type_df,
                use_container_width=True,
                hide_index=True,
            )

        st.markdown("---")

        st.subheader("Динамика проверок")
        trend_df = build_answer_trend_table(answers)

        if trend_df.empty:
            st.info("Пока нет истории проверок.")
        else:
            st.dataframe(
                trend_df.head(14),
                use_container_width=True,
                hide_index=True,
            )

        st.markdown("---")

        st.subheader("Активные сессии")
        active_sessions_df = build_active_sessions_table(
            sessions,
            tasks,
            topic_by_id,
        )

        if active_sessions_df.empty:
            st.success("Нет активных незавершённых сессий.")
        else:
            st.dataframe(
                active_sessions_df,
                use_container_width=True,
                hide_index=True,
            )

        st.markdown("---")

        st.subheader("Слабые места")

        if not mistakes:
            st.info("Ошибок пока нет.")
        else:
            mistake_type_df, mistake_topic_df = build_mistake_tables(
                mistakes,
                topic_by_id,
            )

            col1, col2 = st.columns(2)

            with col1:
                st.markdown("**Топ типов ошибок**")
                st.dataframe(
                    mistake_type_df.head(10),
                    use_container_width=True,
                    hide_index=True,
                )

            with col2:
                st.markdown("**Ошибки по темам**")
                st.dataframe(
                    mistake_topic_df.head(10),
                    use_container_width=True,
                    hide_index=True,
                )

            if not mistake_type_df.empty:
                with st.expander("Частые ошибки"):
                    for _, row in mistake_type_df.head(5).iterrows():
                        st.write(
                            f"- `{row['Тип ошибки']}` — "
                            f"{row['Количество']} раз"
                        )

        st.markdown("---")

        st.subheader("Ближайшие повторения")
        upcoming_df = build_upcoming_table(topics, today_value)

        if upcoming_df.empty:
            st.info("Ближайших повторений нет.")
        else:
            st.dataframe(
                upcoming_df,
                use_container_width=True,
                hide_index=True,
            )

    except Exception as e:
        st.error("Не удалось построить прогресс.")
        st.code(str(e))
