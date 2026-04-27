import json
import random
import re
import time
import uuid
from datetime import date, datetime, timedelta
from typing import Any

import gspread
import streamlit as st
from google import genai
from google.oauth2.service_account import Credentials

from curriculum import GENERAL_CURRICULUM, STAGE_0_CURRICULUM


REPETITION_DAYS = [1, 3, 7, 14, 30]

FALLBACK_MODELS = [
    "gemini-2.5-flash-lite",
    "gemini-2.5-flash",
]

TOPICS_SHEET_NAME = "topics"
SESSIONS_SHEET_NAME = "sessions"
TASKS_SHEET_NAME = "tasks"
ANSWERS_SHEET_NAME = "answers"
MISTAKES_SHEET_NAME = "mistakes"
TASK_FEEDBACK_SHEET_NAME = "task_feedback"


def now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def parse_date(value: str) -> date:
    return datetime.strptime(value, "%Y-%m-%d").date()


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

    # F = learned_date, H = status
    worksheet.update_cell(row_number, 6, learned_date)
    worksheet.update_cell(row_number, 8, status)

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


def update_session_status(session: dict[str, Any], status: str, completed_at: str = "") -> None:
    worksheet = get_worksheet(SESSIONS_SHEET_NAME)
    row_number = session["row_number"]

    # F = completed_at, G = status
    worksheet.update_cell(row_number, 6, completed_at)
    worksheet.update_cell(row_number, 7, status)


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

    # J = status
    worksheet.update_cell(row_number, 10, status)


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


def get_upcoming_repetitions(
    topics: list[dict[str, Any]],
    today: date,
    horizon_days: int = 7,
) -> list[dict[str, Any]]:
    upcoming = []

    for topic in topics:
        if topic.get("status") != "active" or not topic.get("learned_date"):
            continue

        learned_date = parse_date(topic["learned_date"])

        for repetition_day in REPETITION_DAYS:
            repetition_date = learned_date + timedelta(days=repetition_day)

            if today <= repetition_date <= today + timedelta(days=horizon_days):
                upcoming.append(
                    {
                        "date": repetition_date,
                        "topic": topic,
                        "repetition_day": repetition_day,
                    }
                )

    return sorted(upcoming, key=lambda item: item["date"])


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


def get_top_mistakes(mistakes: list[dict[str, Any]], limit: int = 10) -> list[tuple[str, int]]:
    counts: dict[str, int] = {}

    for mistake in mistakes:
        mistake_type = mistake.get("mistake_type") or "unknown"
        counts[mistake_type] = counts.get(mistake_type, 0) + 1

    return sorted(counts.items(), key=lambda item: item[1], reverse=True)[:limit]


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


def get_repetition_info(topic: dict[str, Any], today: date) -> dict[str, Any] | None:
    status = topic.get("status")
    learned_date_value = topic.get("learned_date")

    if status != "active" or not learned_date_value:
        return None

    learned_date = parse_date(learned_date_value)
    days_after_learning = (today - learned_date).days

    if days_after_learning in REPETITION_DAYS:
        return {
            "topic": topic,
            "repetition_day": days_after_learning,
            "learned_date": learned_date,
        }

    return None


def get_today_repetitions(topics: list[dict[str, Any]], today: date) -> list[dict[str, Any]]:
    repetitions = []

    for topic in topics:
        repetition_info = get_repetition_info(topic, today)
        if repetition_info:
            repetitions.append(repetition_info)

    return repetitions


def get_next_repetition(topic: dict[str, Any], today: date) -> str:
    learned_date_value = topic.get("learned_date", "")
    status = topic.get("status", "planned")

    if status == "planned":
        return "тема ещё не отмечена как пройденная"

    if status == "completed":
        return "тема закрыта"

    if status == "paused":
        return "тема на паузе"

    if not learned_date_value:
        return "дата изучения не указана"

    learned_date = parse_date(learned_date_value)
    days_passed = (today - learned_date).days

    if days_passed < 0:
        return f"изучение запланировано на {learned_date.isoformat()}"

    for repetition_day in REPETITION_DAYS:
        if repetition_day >= days_passed:
            next_date = learned_date + timedelta(days=repetition_day)
            return f"день {repetition_day}: {next_date.isoformat()}"

    return "все повторения по этой теме пройдены"


def get_api_key() -> str | None:
    return st.secrets.get("GEMINI_API_KEY")


def get_gemini_client() -> genai.Client | None:
    api_key = get_api_key()

    if not api_key:
        return None

    return genai.Client(api_key=api_key)


def call_gemini_with_retry(prompt: str, models: list[str] | None = None) -> str:
    client = get_gemini_client()

    if client is None:
        raise RuntimeError(
            "Не найден GEMINI_API_KEY в Streamlit secrets. "
            "Добавь его в настройках приложения."
        )

    model_list = models or FALLBACK_MODELS
    last_error = None

    for model in model_list:
        for attempt in range(3):
            try:
                response = client.models.generate_content(
                    model=model,
                    contents=prompt,
                )
                return response.text
            except Exception as e:
                last_error = e
                message = str(e)

                is_overload = (
                    "503" in message
                    or "UNAVAILABLE" in message
                    or "overloaded" in message.lower()
                    or "high demand" in message.lower()
                )

                if not is_overload:
                    raise

                sleep_seconds = min(12, (2 ** attempt) + random.uniform(0, 1.5))
                time.sleep(sleep_seconds)

    raise RuntimeError(
        "Gemini сейчас перегружен или недоступен после нескольких попыток. "
        "Попробуй позже. Последняя ошибка: "
        f"{last_error}"
    )


def build_task_generation_prompt(topic: dict[str, Any], repetition_day: int) -> str:
    known_blocks = ", ".join(str(block) for block in topic.get("known_blocks", []))
    task_feedback_context = get_task_feedback_context(topic["id"])

    return f"""
Ты — эксперт по Python для анализа данных и опытный преподаватель.

Твоя задача — сгенерировать учебные задачи для повторения по кривой Эббингауза.

Контекст верхнеуровневой программы курса:
{GENERAL_CURRICULUM}

Детальная программа этапа 0:
{STAGE_0_CURRICULUM}

Текущая тема:
{topic["stage"]}, блок {topic["block"]}: {topic["title"]}

Краткое описание темы:
{topic["description"]}

Студент уже прошёл блоки:
{known_blocks}

День повторения:
{repetition_day}

Ниже — журнал жалоб пользователя на ранее сгенерированные задачи. Это НЕ ошибки пользователя, а дефекты генерации.
Используй этот журнал как анти-примеры: не повторяй такие проблемы в новых задачах.
Журнал дефектов задач:
{task_feedback_context}

Сгенерируй ровно 40 задач:
- 10 задач на исправление ошибок;
- 10 задач формата "что выведет код?";
- 20 задач на написание кода.

Требования:
- задачи должны проверять именно текущую тему;
- для решения должны требоваться только знания из уже пройденных блоков;
- не давай подсказок в условиях;
- не давай решений;
- не добавляй комментарии-подсказки в код;
- задачи должны быть уникальными;
- для задач типа "debug" в коде ОБЯЗАНА быть реальная ошибка;
- для задач типа "debug" условие НЕ ДОЛЖНО говорить, что код неправильный, если код уже корректен;
- для задач типа "debug" перед выдачей задачи мысленно проверь, что ошибка действительно существует;
- для задач типа "output_prediction" код должен быть корректным и исполняемым, если задача не просит найти ошибку;
- если задача про исправление ошибки, не делай ошибку слишком очевидной через комментарий или текст условия;
- где уместно, используй контекст реальных данных: продажи, маркетинг, HR, финансы, списки клиентов, файлы, простая аналитика;
- формулировки должны быть понятными и короткими;
- язык — русский.

Верни строго валидный JSON без markdown-блока и без пояснений.

Формат JSON:
[
  {{
    "id": 1,
    "type": "debug",
    "difficulty": "начальный",
    "task": "Текст условия",
    "code": "код, если он нужен для задачи"
  }},
  {{
    "id": 11,
    "type": "output_prediction",
    "difficulty": "начальный",
    "task": "Что выведет код?",
    "code": "код для анализа"
  }},
  {{
    "id": 21,
    "type": "write_code",
    "difficulty": "начальный",
    "task": "Напиши код...",
    "code": ""
  }}
]
"""


def build_feedback_prompt(task: dict[str, Any], user_answer: str, topic: dict[str, Any]) -> str:
    code_part = task.get("code", "")

    return f"""
Ты проверяешь решение учебной задачи по Python.

Текущая тема:
{topic["stage"]}, блок {topic["block"]}: {topic["title"]}

Тип задачи:
{task.get("type")}

Условие задачи:
{task.get("task")}

Код из условия, если есть:
```python
{code_part}
```

Ответ пользователя:
```python
{user_answer}
```

Проверь ответ.

Правила обратной связи:
- пиши на русском;
- будь конкретным;
- не растекайся;
- если решение почти верное, не переписывай весь код, дай точечную правку;
- если решение неверное, объясни ошибку и дай маленькую подсказку;
- если это задача "что выведет код?", проверь не только результат, но и ход рассуждения;
- если это задача на исправление ошибок, проверь, исправлена ли исходная проблема.

Верни строго валидный JSON без markdown-блока и без пояснений.

Формат JSON:
{{
  "verdict": "correct | partially_correct | incorrect",
  "feedback": "Текст обратной связи на русском языке",
  "mistake_type": "короткий тип ошибки, например missing_return, wrong_loop_condition, syntax_error, no_mistake",
  "mistake_summary": "короткое описание ошибки или пустая строка"
}}
"""


def extract_json_from_gemini(text: str) -> Any:
    clean_text = text.strip()

    if clean_text.startswith("```json"):
        clean_text = clean_text.removeprefix("```json").strip()

    if clean_text.startswith("```"):
        clean_text = clean_text.removeprefix("```").strip()

    if clean_text.endswith("```"):
        clean_text = clean_text.removesuffix("```").strip()

    return json.loads(clean_text)


def extract_feedback_json(text: str) -> dict[str, str]:
    try:
        parsed = extract_json_from_gemini(text)
        return {
            "verdict": normalize_verdict(parsed.get("verdict", "")),
            "feedback": normalize_cell(parsed.get("feedback", text)),
            "mistake_type": normalize_cell(parsed.get("mistake_type", "")),
            "mistake_summary": normalize_cell(parsed.get("mistake_summary", "")),
        }
    except Exception:
        return {
            "verdict": infer_verdict_from_text(text),
            "feedback": text,
            "mistake_type": "",
            "mistake_summary": "",
        }


def normalize_verdict(value: str) -> str:
    value = normalize_cell(value).lower()

    if value in ["correct", "корректно", "правильно"]:
        return "correct"

    if value in ["partially_correct", "partial", "частично корректно", "частично"]:
        return "partially_correct"

    if value in ["incorrect", "некорректно", "неправильно"]:
        return "incorrect"

    return value or "unknown"


def infer_verdict_from_text(text: str) -> str:
    lowered = text.lower()

    if "частично" in lowered:
        return "partially_correct"

    if "некоррект" in lowered or "неправ" in lowered or "ошиб" in lowered:
        return "incorrect"

    if "коррект" in lowered or "правиль" in lowered:
        return "correct"

    return "unknown"


def generate_tasks(topic: dict[str, Any], repetition_day: int) -> list[dict[str, Any]]:
    response_text = call_gemini_with_retry(
        build_task_generation_prompt(topic, repetition_day),
        models=FALLBACK_MODELS,
    )
    return extract_json_from_gemini(response_text)


def get_feedback_json(task: dict[str, Any], user_answer: str, topic: dict[str, Any]) -> dict[str, str]:
    response_text = call_gemini_with_retry(
        build_feedback_prompt(task, user_answer, topic),
        models=FALLBACK_MODELS,
    )
    return extract_feedback_json(response_text)


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


def load_session_into_state(session: dict[str, Any]) -> None:
    tasks = get_tasks_for_session(session["session_id"])
    current_index = get_first_unanswered_index(tasks)

    st.session_state["current_session_id"] = session["session_id"]
    st.session_state["tasks"] = tasks
    st.session_state["current_task_index"] = current_index
    st.session_state["last_feedback"] = ""
    st.session_state["last_verdict"] = ""
    st.session_state["user_answer"] = ""


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


def build_progress_stats(
    topics: list[dict[str, Any]],
    sessions: list[dict[str, Any]],
    tasks: list[dict[str, Any]],
    answers: list[dict[str, Any]],
) -> dict[str, Any]:
    topic_by_id = {topic["id"]: topic for topic in topics}
    tasks_by_id = {task["task_id"]: task for task in tasks}

    total_tasks = len(tasks)
    answered_tasks = len([task for task in tasks if task.get("status") == "answered"])

    verdict_counts = {
        "correct": 0,
        "partially_correct": 0,
        "incorrect": 0,
        "unknown": 0,
    }

    for answer in answers:
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
                "correct": 0,
                "partial": 0,
                "incorrect": 0,
            }

        topic_stats[topic_id]["total"] += 1

        if task.get("status") == "answered":
            topic_stats[topic_id]["answered"] += 1

    for answer in answers:
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
        "sessions_count": len(sessions),
        "answers_count": len(answers),
        "verdict_counts": verdict_counts,
        "topic_stats": topic_stats,
    }


st.set_page_config(page_title="Python Trainer", page_icon="🐍", layout="centered")

st.title("Python Trainer")
st.write("Google Sheets как база + удобная сессия + прогресс и ошибки.")

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
    st.caption("Дни повторения: 1, 3, 7, 14, 30.")
    st.caption(f"Модели Gemini: {', '.join(FALLBACK_MODELS)}")

try:
    topics = load_topics()
except Exception as e:
    st.error("Не удалось прочитать Google Sheet.")
    st.write("Если видишь 429 quota exceeded — это лимит чтения Google Sheets. Подожди 1–2 минуты и нажми «Перечитать Google Sheet». В этой версии чтение кэшируется на 60 секунд.")
    st.code(str(e))
    st.stop()

tab_today, tab_plan, tab_sessions, tab_progress = st.tabs(
    ["Сегодня", "Учебный план", "Сессии", "Прогресс"]
)

with tab_plan:
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

with tab_sessions:
    st.header("Сессии")

    try:
        sessions = load_sessions()
        tasks = load_tasks()
        answers = load_answers()

        if not sessions:
            st.info("Сессий пока нет.")
        else:
            answers_by_task_id = get_answers_by_task_id()

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

with tab_progress:
    st.header("Прогресс")

    try:
        sessions = load_sessions()
        tasks = load_tasks()
        answers = load_answers()
        mistakes = load_mistakes()
        stats = build_progress_stats(topics, sessions, tasks, answers)

        col1, col2, col3 = st.columns(3)
        col1.metric("Сессий", stats["sessions_count"])
        col2.metric("Задач решено", f"{stats['answered_tasks']}/{stats['total_tasks']}")
        col3.metric("Ответов сохранено", stats["answers_count"])

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
                f"ошибки: {topic_stat['incorrect']}"
            )
            st.progress(ratio)

    except Exception as e:
        st.error("Не удалось построить прогресс.")
        st.code(str(e))

with tab_today:
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
                    generated_tasks = generate_tasks(
                        selected_topic,
                        selected_repetition_day,
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

    tasks = st.session_state["tasks"]
    current_task_index = st.session_state.get("current_task_index", 0)
    progress = get_session_progress(tasks)

    st.markdown("### Прогресс сессии")
    st.progress((progress["answered"] + progress["skipped"]) / progress["total"])
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

    user_answer = st.text_area(
        "Твой ответ",
        value=st.session_state.get("user_answer", ""),
        height=260,
        key="answer_input",
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
            disabled=current_task.get("status") in ["answered", "bad_task"],
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


    if st.session_state.get("last_feedback"):
        st.markdown("### Фидбек Gemini")
        st.caption(f"Вердикт: {st.session_state.get('last_verdict', 'unknown')}")
        st.markdown(st.session_state["last_feedback"])
