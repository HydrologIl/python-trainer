import uuid
from datetime import datetime
from typing import Any

import gspread
import streamlit as st
from google.oauth2.service_account import Credentials

from gemini_service import normalize_verdict


TOPICS_SHEET_NAME = "topics"
SESSIONS_SHEET_NAME = "sessions"
TASKS_SHEET_NAME = "tasks"
ANSWERS_SHEET_NAME = "answers"
MISTAKES_SHEET_NAME = "mistakes"
TASK_FEEDBACK_SHEET_NAME = "task_feedback"
DATASETS_SHEET_NAME = "datasets"


def now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def normalize_cell(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def parse_known_blocks(value: Any) -> list[int]:
    text = normalize_cell(value)
    if not text:
        return []

    result = []
    for part in text.split(","):
        part = part.strip()
        if part.isdigit():
            result.append(int(part))
    return result


@st.cache_resource(ttl=300)
def get_spreadsheet() -> gspread.Spreadsheet:
    sheet_id = st.secrets.get("GOOGLE_SHEET_ID")

    if not sheet_id:
        raise RuntimeError("Не найден GOOGLE_SHEET_ID в Streamlit secrets.")

    service_account_info = dict(st.secrets["gcp_service_account"])

    scopes = [
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive",
    ]

    credentials = Credentials.from_service_account_info(
        service_account_info,
        scopes=scopes,
    )

    client = gspread.authorize(credentials)
    return client.open_by_key(sheet_id)


def get_worksheet(name: str) -> gspread.Worksheet:
    spreadsheet = get_spreadsheet()
    return spreadsheet.worksheet(name)


def get_or_create_worksheet(name: str, headers: list[str]) -> gspread.Worksheet:
    spreadsheet = get_spreadsheet()

    try:
        worksheet = spreadsheet.worksheet(name)
    except gspread.WorksheetNotFound:
        worksheet = spreadsheet.add_worksheet(
            title=name,
            rows=1000,
            cols=max(len(headers), 10),
        )
        worksheet.append_row(headers, value_input_option="USER_ENTERED")
        return worksheet

    existing_headers = worksheet.row_values(1)
    if not existing_headers:
        worksheet.append_row(headers, value_input_option="USER_ENTERED")

    return worksheet


@st.cache_data(ttl=60)
def load_topics() -> list[dict[str, Any]]:
    worksheet = get_worksheet(TOPICS_SHEET_NAME)
    records = worksheet.get_all_records()

    topics = []

    for index, record in enumerate(records, start=2):
        topic_id = normalize_cell(record.get("topic_id"))

        if not topic_id:
            continue

        topics.append(
            {
                "row_number": index,
                "id": topic_id,
                "stage": normalize_cell(record.get("stage")),
                "block": int(record.get("block") or 0),
                "title": normalize_cell(record.get("title")),
                "description": normalize_cell(record.get("description")),
                "learned_date": normalize_cell(record.get("learned_date")),
                "known_blocks": parse_known_blocks(record.get("known_blocks")),
                "status": normalize_cell(record.get("status")) or "planned",
            }
        )

    return topics


def update_topic(topic: dict[str, Any], learned_date: str, status: str) -> None:
    worksheet = get_worksheet(TOPICS_SHEET_NAME)
    row_number = topic["row_number"]

    worksheet.update_cell(row_number, 6, learned_date)
    worksheet.update_cell(row_number, 8, status)

    st.cache_data.clear()
    st.cache_resource.clear()


@st.cache_data(ttl=60)
def load_sessions() -> list[dict[str, Any]]:
    worksheet = get_worksheet(SESSIONS_SHEET_NAME)
    records = worksheet.get_all_records()

    sessions = []

    for index, record in enumerate(records, start=2):
        session_id = normalize_cell(record.get("session_id"))

        if not session_id:
            continue

        sessions.append(
            {
                "row_number": index,
                "session_id": session_id,
                "topic_id": normalize_cell(record.get("topic_id")),
                "repetition_day": int(record.get("repetition_day") or 0),
                "scheduled_date": normalize_cell(record.get("scheduled_date")),
                "started_at": normalize_cell(record.get("started_at")),
                "completed_at": normalize_cell(record.get("completed_at")),
                "status": normalize_cell(record.get("status")) or "planned",
            }
        )

    return sessions


def update_session_status(
    session: dict[str, Any],
    status: str,
    completed_at: str = "",
) -> None:
    worksheet = get_worksheet(SESSIONS_SHEET_NAME)
    row_number = session["row_number"]

    worksheet.update_cell(row_number, 6, completed_at)
    worksheet.update_cell(row_number, 7, status)
    st.cache_data.clear()


@st.cache_data(ttl=60)
def load_tasks() -> list[dict[str, Any]]:
    worksheet = get_worksheet(TASKS_SHEET_NAME)
    records = worksheet.get_all_records()

    tasks = []

    for index, record in enumerate(records, start=2):
        task_id = normalize_cell(record.get("task_id"))

        if not task_id:
            continue

        tasks.append(
            {
                "row_number": index,
                "task_id": task_id,
                "session_id": normalize_cell(record.get("session_id")),
                "topic_id": normalize_cell(record.get("topic_id")),
                "repetition_day": int(record.get("repetition_day") or 0),
                "type": normalize_cell(record.get("task_type")),
                "difficulty": normalize_cell(record.get("difficulty")),
                "task": normalize_cell(record.get("task_text")),
                "code": normalize_cell(record.get("code")),
                "order": int(record.get("order") or 0),
                "status": normalize_cell(record.get("status")) or "new",
                "created_at": normalize_cell(record.get("created_at")),
            }
        )

    return tasks


def update_task_status(task: dict[str, Any], status: str) -> None:
    worksheet = get_worksheet(TASKS_SHEET_NAME)
    row_number = task["row_number"]

    worksheet.update_cell(row_number, 10, status)
    st.cache_data.clear()


def skip_task(task: dict[str, Any]) -> None:
    update_task_status(task, "skipped")


def mark_bad_task(task: dict[str, Any]) -> None:
    update_task_status(task, "bad_task")


@st.cache_data(ttl=60)
def load_answers() -> list[dict[str, Any]]:
    worksheet = get_worksheet(ANSWERS_SHEET_NAME)
    records = worksheet.get_all_records()

    answers = []

    for index, record in enumerate(records, start=2):
        answer_id = normalize_cell(record.get("answer_id"))

        if not answer_id:
            continue

        answers.append(
            {
                "row_number": index,
                "answer_id": answer_id,
                "task_id": normalize_cell(record.get("task_id")),
                "user_answer": normalize_cell(record.get("user_answer")),
                "gemini_feedback": normalize_cell(record.get("gemini_feedback")),
                "verdict": normalize_cell(record.get("verdict")),
                "created_at": normalize_cell(record.get("created_at")),
            }
        )

    return answers


def save_answer(
    task: dict[str, Any],
    user_answer: str,
    feedback: str,
    verdict: str,
) -> str:
    answer_id = f"answer_{uuid.uuid4().hex[:12]}"

    worksheet = get_worksheet(ANSWERS_SHEET_NAME)
    worksheet.append_row(
        [
            answer_id,
            task["task_id"],
            user_answer,
            feedback,
            verdict,
            now_iso(),
        ],
        value_input_option="USER_ENTERED",
    )

    st.cache_data.clear()
    return answer_id


@st.cache_data(ttl=60)
def load_mistakes() -> list[dict[str, Any]]:
    worksheet = get_worksheet(MISTAKES_SHEET_NAME)
    records = worksheet.get_all_records()

    mistakes = []

    for index, record in enumerate(records, start=2):
        mistake_id = normalize_cell(record.get("mistake_id"))

        if not mistake_id:
            continue

        mistakes.append(
            {
                "row_number": index,
                "mistake_id": mistake_id,
                "topic_id": normalize_cell(record.get("topic_id")),
                "task_id": normalize_cell(record.get("task_id")),
                "mistake_type": normalize_cell(record.get("mistake_type")),
                "mistake_summary": normalize_cell(record.get("mistake_summary")),
                "created_at": normalize_cell(record.get("created_at")),
            }
        )

    return mistakes


def save_mistake(
    topic: dict[str, Any],
    task: dict[str, Any],
    mistake_type: str,
    mistake_summary: str,
) -> None:
    if not mistake_summary and not mistake_type:
        return

    if normalize_verdict(mistake_type) == "correct":
        return

    mistake_id = f"mistake_{uuid.uuid4().hex[:12]}"

    worksheet = get_worksheet(MISTAKES_SHEET_NAME)
    worksheet.append_row(
        [
            mistake_id,
            topic["id"],
            task["task_id"],
            mistake_type,
            mistake_summary,
            now_iso(),
        ],
        value_input_option="USER_ENTERED",
    )

    st.cache_data.clear()


@st.cache_data(ttl=60)
def load_task_feedback() -> list[dict[str, Any]]:
    worksheet = get_or_create_worksheet(
        TASK_FEEDBACK_SHEET_NAME,
        [
            "feedback_id",
            "task_id",
            "session_id",
            "topic_id",
            "issue_type",
            "comment",
            "created_at",
        ],
    )

    records = worksheet.get_all_records()
    feedback_items = []

    for index, record in enumerate(records, start=2):
        feedback_id = normalize_cell(record.get("feedback_id"))

        if not feedback_id:
            continue

        feedback_items.append(
            {
                "row_number": index,
                "feedback_id": feedback_id,
                "task_id": normalize_cell(record.get("task_id")),
                "session_id": normalize_cell(record.get("session_id")),
                "topic_id": normalize_cell(record.get("topic_id")),
                "issue_type": normalize_cell(record.get("issue_type")),
                "comment": normalize_cell(record.get("comment")),
                "created_at": normalize_cell(record.get("created_at")),
            }
        )

    return feedback_items


def save_task_feedback(
    task: dict[str, Any],
    issue_type: str,
    comment: str,
) -> None:
    worksheet = get_or_create_worksheet(
        TASK_FEEDBACK_SHEET_NAME,
        [
            "feedback_id",
            "task_id",
            "session_id",
            "topic_id",
            "issue_type",
            "comment",
            "created_at",
        ],
    )

    worksheet.append_row(
        [
            f"feedback_{uuid.uuid4().hex[:12]}",
            task["task_id"],
            task["session_id"],
            task["topic_id"],
            issue_type,
            comment,
            now_iso(),
        ],
        value_input_option="USER_ENTERED",
    )

    st.cache_data.clear()


def get_task_feedback_context(topic_id: str, limit: int = 12) -> str:
    try:
        feedback_items = load_task_feedback()
    except Exception:
        return "Пока нет сохранённых жалоб на задачи."

    relevant = [
        item for item in feedback_items
        if item.get("topic_id") == topic_id
    ]

    general = [
        item for item in feedback_items
        if item.get("topic_id") != topic_id
    ]

    selected_items = (relevant[-limit:] + general[-max(0, limit - len(relevant)):])[-limit:]

    if not selected_items:
        return "Пока нет сохранённых жалоб на задачи."

    lines = []

    for item in selected_items:
        comment = item.get("comment") or "без комментария"
        lines.append(
            f"- Тип проблемы: {item.get('issue_type')}. Комментарий пользователя: {comment}"
        )

    return "\n".join(lines)




@st.cache_data(ttl=60)
def load_datasets() -> list[dict[str, Any]]:
    worksheet = get_or_create_worksheet(
        DATASETS_SHEET_NAME,
        [
            "dataset_id",
            "name",
            "domain",
            "description",
            "tables",
            "columns",
            "example_rows",
            "best_for_topics",
            "difficulty",
            "source",
            "status",
        ],
    )

    records = worksheet.get_all_records()
    datasets = []

    for index, record in enumerate(records, start=2):
        dataset_id = normalize_cell(record.get("dataset_id"))

        if not dataset_id:
            continue

        datasets.append(
            {
                "row_number": index,
                "dataset_id": dataset_id,
                "name": normalize_cell(record.get("name")),
                "domain": normalize_cell(record.get("domain")),
                "description": normalize_cell(record.get("description")),
                "tables": normalize_cell(record.get("tables")),
                "columns": normalize_cell(record.get("columns")),
                "example_rows": normalize_cell(record.get("example_rows")),
                "best_for_topics": normalize_cell(record.get("best_for_topics")),
                "difficulty": normalize_cell(record.get("difficulty")),
                "source": normalize_cell(record.get("source")),
                "status": normalize_cell(record.get("status")) or "active",
            }
        )

    return datasets


def get_active_datasets() -> list[dict[str, Any]]:
    return [
        dataset for dataset in load_datasets()
        if dataset.get("status") == "active"
    ]


def find_session(
    topic_id: str,
    repetition_day: int,
    scheduled_date: str,
) -> dict[str, Any] | None:
    sessions = load_sessions()

    for session in sessions:
        if (
            session["topic_id"] == topic_id
            and session["repetition_day"] == repetition_day
            and session["scheduled_date"] == scheduled_date
            and session["status"] != "deleted"
        ):
            return session

    return None


def get_tasks_for_session(session_id: str) -> list[dict[str, Any]]:
    tasks = [
        task
        for task in load_tasks()
        if task["session_id"] == session_id
    ]
    return sorted(tasks, key=lambda task: task["order"])


def get_answers_by_task_id() -> dict[str, list[dict[str, Any]]]:
    result: dict[str, list[dict[str, Any]]] = {}

    for answer in load_answers():
        result.setdefault(answer["task_id"], []).append(answer)

    return result


def get_latest_answer_for_task(task_id: str) -> dict[str, Any] | None:
    answers = get_answers_by_task_id().get(task_id, [])

    if not answers:
        return None

    return sorted(answers, key=lambda answer: answer.get("created_at", ""))[-1]


def get_session_progress(tasks: list[dict[str, Any]]) -> dict[str, int]:
    total = len(tasks)
    answered = len([task for task in tasks if task.get("status") == "answered"])
    skipped = len([task for task in tasks if task.get("status") == "skipped"])
    bad_tasks = len([task for task in tasks if task.get("status") == "bad_task"])
    remaining = total - answered - skipped - bad_tasks

    return {
        "total": total,
        "answered": answered,
        "skipped": skipped,
        "bad_tasks": bad_tasks,
        "remaining": remaining,
    }


def get_first_unanswered_index(tasks: list[dict[str, Any]]) -> int:
    closed_statuses = {"answered", "skipped", "bad_task"}

    for index, task in enumerate(tasks):
        if task.get("status") not in closed_statuses:
            return index

    return len(tasks)


def create_session(
    topic_id: str,
    repetition_day: int,
    scheduled_date: str,
) -> str:
    session_id = f"session_{uuid.uuid4().hex[:12]}"

    worksheet = get_worksheet(SESSIONS_SHEET_NAME)
    worksheet.append_row(
        [
            session_id,
            topic_id,
            repetition_day,
            scheduled_date,
            now_iso(),
            "",
            "in_progress",
        ],
        value_input_option="USER_ENTERED",
    )

    st.cache_data.clear()
    return session_id


def save_generated_tasks(
    session_id: str,
    topic: dict[str, Any],
    repetition_day: int,
    generated_tasks: list[dict[str, Any]],
) -> None:
    worksheet = get_worksheet(TASKS_SHEET_NAME)

    rows = []

    for index, task in enumerate(generated_tasks, start=1):
        task_id = f"task_{uuid.uuid4().hex[:12]}"

        rows.append(
            [
                task_id,
                session_id,
                topic["id"],
                repetition_day,
                normalize_cell(task.get("type")),
                normalize_cell(task.get("difficulty")),
                normalize_cell(task.get("task")),
                normalize_cell(task.get("code")),
                index,
                "new",
                now_iso(),
            ]
        )

    worksheet.append_rows(rows, value_input_option="USER_ENTERED")
    st.cache_data.clear()


def get_top_mistakes(mistakes: list[dict[str, Any]], limit: int = 10) -> list[tuple[str, int]]:
    counts: dict[str, int] = {}

    for mistake in mistakes:
        mistake_type = mistake.get("mistake_type") or "unknown"
        counts[mistake_type] = counts.get(mistake_type, 0) + 1

    return sorted(counts.items(), key=lambda item: item[1], reverse=True)[:limit]


def build_progress_stats(
    topics: list[dict[str, Any]],
    sessions: list[dict[str, Any]],
    tasks: list[dict[str, Any]],
    answers: list[dict[str, Any]],
) -> dict[str, Any]:
    topic_by_id = {topic["id"]: topic for topic in topics}
    tasks_by_id = {task["task_id"]: task for task in tasks}

    valid_tasks = [
        task for task in tasks
        if task.get("status") != "bad_task"
    ]

    bad_tasks_count = len(tasks) - len(valid_tasks)

    total_tasks = len(valid_tasks)
    answered_tasks = len([
        task for task in valid_tasks
        if task.get("status") == "answered"
    ])

    verdict_counts = {
        "correct": 0,
        "partially_correct": 0,
        "incorrect": 0,
        "unknown": 0,
    }

    valid_task_ids = {task["task_id"] for task in valid_tasks}
    valid_answers = [
        answer for answer in answers
        if answer.get("task_id") in valid_task_ids
    ]

    for answer in valid_answers:
        verdict = normalize_verdict(answer.get("verdict", "unknown"))
        if verdict not in verdict_counts:
            verdict = "unknown"
        verdict_counts[verdict] += 1

    topic_stats: dict[str, dict[str, Any]] = {}

    for task in tasks:
        topic_id = task["topic_id"]
        topic = topic_by_id.get(topic_id)
        topic_title = topic["title"] if topic else topic_id

        if topic_id not in topic_stats:
            topic_stats[topic_id] = {
                "title": topic_title,
                "total": 0,
                "answered": 0,
                "bad_tasks": 0,
                "correct": 0,
                "partial": 0,
                "incorrect": 0,
            }

        if task.get("status") == "bad_task":
            topic_stats[topic_id]["bad_tasks"] += 1
            continue

        topic_stats[topic_id]["total"] += 1

        if task.get("status") == "answered":
            topic_stats[topic_id]["answered"] += 1

    for answer in valid_answers:
        task = tasks_by_id.get(answer["task_id"])
        if not task:
            continue

        topic_id = task["topic_id"]
        verdict = normalize_verdict(answer.get("verdict", "unknown"))

        if topic_id not in topic_stats:
            continue

        if verdict == "correct":
            topic_stats[topic_id]["correct"] += 1
        elif verdict == "partially_correct":
            topic_stats[topic_id]["partial"] += 1
        elif verdict == "incorrect":
            topic_stats[topic_id]["incorrect"] += 1

    return {
        "total_tasks": total_tasks,
        "answered_tasks": answered_tasks,
        "bad_tasks_count": bad_tasks_count,
        "sessions_count": len(sessions),
        "answers_count": len(valid_answers),
        "verdict_counts": verdict_counts,
        "topic_stats": topic_stats,
    }
