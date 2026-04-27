import json
import random
import time
from datetime import date, datetime, timedelta
from typing import Any

import gspread
import streamlit as st
from google import genai
from google.oauth2.service_account import Credentials

from curriculum import GENERAL_CURRICULUM, STAGE_0_CURRICULUM

REPETITION_DAYS = [1, 3, 7, 14, 30]
FALLBACK_MODELS = ["gemini-2.5-flash-lite", "gemini-2.5-flash"]
TOPICS_SHEET_NAME = "topics"


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
    credentials = Credentials.from_service_account_info(service_account_info, scopes=scopes)
    client = gspread.authorize(credentials)
    return client.open_by_key(sheet_id)


def get_topics_worksheet() -> gspread.Worksheet:
    return get_spreadsheet().worksheet(TOPICS_SHEET_NAME)


def load_topics() -> list[dict[str, Any]]:
    worksheet = get_topics_worksheet()
    records = worksheet.get_all_records()
    topics = []
    for index, record in enumerate(records, start=2):
        topic_id = normalize_cell(record.get("topic_id"))
        if not topic_id:
            continue
        topics.append({
            "row_number": index,
            "id": topic_id,
            "stage": normalize_cell(record.get("stage")),
            "block": int(record.get("block") or 0),
            "title": normalize_cell(record.get("title")),
            "description": normalize_cell(record.get("description")),
            "learned_date": normalize_cell(record.get("learned_date")),
            "known_blocks": parse_known_blocks(record.get("known_blocks")),
            "status": normalize_cell(record.get("status")) or "planned",
        })
    return topics


def update_topic(topic: dict[str, Any], learned_date: str, status: str) -> None:
    worksheet = get_topics_worksheet()
    row_number = topic["row_number"]
    # F = learned_date, H = status
    worksheet.update_cell(row_number, 6, learned_date)
    worksheet.update_cell(row_number, 8, status)
    st.cache_resource.clear()


def get_repetition_info(topic: dict[str, Any], today: date) -> dict[str, Any] | None:
    status = topic.get("status")
    learned_date_value = topic.get("learned_date")
    if status != "active" or not learned_date_value:
        return None
    learned_date = parse_date(learned_date_value)
    days_after_learning = (today - learned_date).days
    if days_after_learning in REPETITION_DAYS:
        return {"topic": topic, "repetition_day": days_after_learning, "learned_date": learned_date}
    return None


def get_today_repetitions(topics: list[dict[str, Any]], today: date) -> list[dict[str, Any]]:
    return [info for topic in topics if (info := get_repetition_info(topic, today))]


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


def get_gemini_client() -> genai.Client | None:
    api_key = st.secrets.get("GEMINI_API_KEY")
    if not api_key:
        return None
    return genai.Client(api_key=api_key)


def call_gemini_with_retry(prompt: str, models: list[str] | None = None) -> str:
    client = get_gemini_client()
    if client is None:
        raise RuntimeError("Не найден GEMINI_API_KEY в Streamlit secrets.")
    model_list = models or FALLBACK_MODELS
    last_error = None
    for model in model_list:
        for attempt in range(3):
            try:
                response = client.models.generate_content(model=model, contents=prompt)
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
                time.sleep(min(12, (2 ** attempt) + random.uniform(0, 1.5)))
    raise RuntimeError(f"Gemini сейчас перегружен или недоступен. Последняя ошибка: {last_error}")


def build_task_generation_prompt(topic: dict[str, Any], repetition_day: int) -> str:
    known_blocks = ", ".join(str(block) for block in topic.get("known_blocks", []))
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
- где уместно, используй контекст реальных данных: продажи, маркетинг, HR, финансы, списки клиентов, файлы, простая аналитика;
- формулировки должны быть понятными и короткими;
- язык — русский.

Верни строго валидный JSON без markdown-блока и без пояснений.

Формат JSON:
[
  {{"id": 1, "type": "debug", "difficulty": "начальный", "task": "Текст условия", "code": "код, если он нужен для задачи"}},
  {{"id": 11, "type": "output_prediction", "difficulty": "начальный", "task": "Что выведет код?", "code": "код для анализа"}},
  {{"id": 21, "type": "write_code", "difficulty": "начальный", "task": "Напиши код...", "code": ""}}
]
"""


def build_feedback_prompt(task: dict[str, Any], user_answer: str, topic: dict[str, Any]) -> str:
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
{task.get("code", "")}
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

Ответь в формате:
1. Вердикт: корректно / частично корректно / некорректно.
2. Что хорошо.
3. Что исправить.
4. Мини-подсказка или следующий шаг.
"""


def extract_json_from_gemini(text: str) -> list[dict[str, Any]]:
    clean_text = text.strip()
    if clean_text.startswith("```json"):
        clean_text = clean_text.removeprefix("```json").strip()
    if clean_text.startswith("```"):
        clean_text = clean_text.removeprefix("```").strip()
    if clean_text.endswith("```"):
        clean_text = clean_text.removesuffix("```").strip()
    return json.loads(clean_text)


def generate_tasks(topic: dict[str, Any], repetition_day: int) -> list[dict[str, Any]]:
    response_text = call_gemini_with_retry(build_task_generation_prompt(topic, repetition_day))
    return extract_json_from_gemini(response_text)


def get_feedback(task: dict[str, Any], user_answer: str, topic: dict[str, Any]) -> str:
    return call_gemini_with_retry(build_feedback_prompt(task, user_answer, topic))


def reset_session() -> None:
    for key in ["tasks", "current_task_index", "selected_topic_id", "selected_repetition_day", "last_feedback", "user_answer", "answer_input"]:
        if key in st.session_state:
            del st.session_state[key]


def render_task(task: dict[str, Any], index: int, total: int) -> None:
    task_type_labels = {
        "debug": "Исправление ошибок",
        "output_prediction": "Что выведет код?",
        "write_code": "Написание кода",
    }
    task_type = task_type_labels.get(task.get("type"), task.get("type", "Задача"))
    st.markdown(f"### Задача {index + 1} из {total}")
    st.caption(f"{task_type} · сложность: {task.get('difficulty', 'не указана')}")
    st.write(task.get("task", ""))
    if task.get("code"):
        st.code(task["code"], language="python")


st.set_page_config(page_title="Python Trainer", page_icon="🐍", layout="centered")
st.title("Python Trainer")
st.write("Google Sheets как база тем + повторения по Эббингаузу + проверка через Gemini.")

with st.sidebar:
    st.header("Настройки")
    today_value = st.date_input("Дата для расчёта повторений", value=date.today())
    if st.button("Сбросить текущую сессию задач"):
        reset_session()
        st.rerun()
    if st.button("Перечитать Google Sheet"):
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
    st.write("Проверь GOOGLE_SHEET_ID, gcp_service_account в Streamlit secrets и доступ Editor для service account.")
    st.code(str(e))
    st.stop()

tab_today, tab_plan = st.tabs(["Сегодня", "Учебный план"])

with tab_plan:
    st.header("Учебный план")
    st.info("Темы, статусы и даты теперь читаются из Google Sheets. Изменения сохраняются обратно в лист topics.")

    selected_topic_for_edit = st.selectbox(
        "Тема",
        topics,
        format_func=lambda topic: f"Блок {topic['block']}. {topic['title']}",
    )

    current_status = selected_topic_for_edit.get("status", "planned")
    if current_status not in ["planned", "active", "completed", "paused"]:
        current_status = "planned"

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

    current_learned_date = selected_topic_for_edit.get("learned_date", "")
    default_date = parse_date(current_learned_date) if current_learned_date else today_value
    learned_date_input = st.date_input("Дата изучения темы", value=default_date)

    col_a, col_b = st.columns(2)
    with col_a:
        if st.button("Сохранить дату и статус"):
            try:
                update_topic(selected_topic_for_edit, learned_date_input.isoformat(), status)
                reset_session()
                st.success("Сохранено в Google Sheets.")
                st.rerun()
            except Exception as e:
                st.error("Не удалось сохранить изменения.")
                st.code(str(e))
    with col_b:
        if st.button("Отметить как пройденную сегодня"):
            try:
                update_topic(selected_topic_for_edit, today_value.isoformat(), "active")
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
        st.session_state["tasks"] = []
        st.session_state["current_task_index"] = 0
        st.session_state["last_feedback"] = ""
        st.session_state["user_answer"] = ""
        st.session_state["selected_topic_id"] = selected_topic["id"]
        st.session_state["selected_repetition_day"] = selected_repetition_day

    if not st.session_state.get("tasks"):
        if st.button("Начать сессию и сгенерировать задачи"):
            with st.spinner("Gemini генерирует 40 задач..."):
                try:
                    st.session_state["tasks"] = generate_tasks(selected_topic, selected_repetition_day)
                    st.session_state["current_task_index"] = 0
                    st.session_state["last_feedback"] = ""
                    st.session_state["user_answer"] = ""
                    st.rerun()
                except Exception as e:
                    st.error("Не удалось сгенерировать задачи.")
                    st.code(str(e))
        st.stop()

    tasks = st.session_state["tasks"]
    current_task_index = st.session_state.get("current_task_index", 0)
    if current_task_index >= len(tasks):
        st.success("Сессия завершена. Все задачи пройдены.")
        if st.button("Начать заново"):
            reset_session()
            st.rerun()
        st.stop()

    current_task = tasks[current_task_index]
    render_task(current_task, current_task_index, len(tasks))

    user_answer = st.text_area(
        "Твой ответ",
        value=st.session_state.get("user_answer", ""),
        height=260,
        key="answer_input",
    )

    col1, col2 = st.columns(2)
    with col1:
        if st.button("Проверить"):
            if not user_answer.strip():
                st.warning("Сначала напиши ответ.")
            else:
                with st.spinner("Gemini проверяет ответ..."):
                    try:
                        feedback = get_feedback(current_task, user_answer, selected_topic)
                        st.session_state["last_feedback"] = feedback
                        st.session_state["user_answer"] = user_answer
                        st.rerun()
                    except Exception as e:
                        st.error("Не удалось получить фидбек.")
                        st.code(str(e))
    with col2:
        if st.button("Следующая задача"):
            st.session_state["current_task_index"] = current_task_index + 1
            st.session_state["last_feedback"] = ""
            st.session_state["user_answer"] = ""
            st.rerun()

    if st.session_state.get("last_feedback"):
        st.markdown("### Фидбек Gemini")
        st.markdown(st.session_state["last_feedback"])
