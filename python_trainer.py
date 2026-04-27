import json
from datetime import date, datetime, timedelta
from typing import Any

import streamlit as st
from google import genai

from curriculum import GENERAL_CURRICULUM, STAGE_0_CURRICULUM, TOPICS


REPETITION_DAYS = [1, 3, 7, 14, 30]


def parse_date(value: str) -> date:
    return datetime.strptime(value, "%Y-%m-%d").date()


def get_repetition_info(topic: dict[str, Any], today: date) -> dict[str, Any] | None:
    learned_date = parse_date(topic["learned_date"])
    days_after_learning = (today - learned_date).days

    if days_after_learning in REPETITION_DAYS:
        return {
            "topic": topic,
            "repetition_day": days_after_learning,
            "learned_date": learned_date,
        }

    return None


def get_today_repetitions(today: date) -> list[dict[str, Any]]:
    repetitions = []

    for topic in TOPICS:
        if topic.get("status") != "active":
            continue

        repetition_info = get_repetition_info(topic, today)
        if repetition_info:
            repetitions.append(repetition_info)

    return repetitions


def get_gemini_client() -> genai.Client | None:
    api_key = st.secrets.get("GEMINI_API_KEY")

    if not api_key:
        return None

    return genai.Client(api_key=api_key)


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
    client = get_gemini_client()

    if client is None:
        raise RuntimeError(
            "Не найден GEMINI_API_KEY в Streamlit secrets. "
            "Добавь его в настройках приложения."
        )

    response = client.models.generate_content(
        model="gemini-2.5-flash",
        contents=build_task_generation_prompt(topic, repetition_day),
    )

    return extract_json_from_gemini(response.text)


def get_feedback(task: dict[str, Any], user_answer: str, topic: dict[str, Any]) -> str:
    client = get_gemini_client()

    if client is None:
        raise RuntimeError(
            "Не найден GEMINI_API_KEY в Streamlit secrets. "
            "Добавь его в настройках приложения."
        )

    response = client.models.generate_content(
        model="gemini-2.5-flash",
        contents=build_feedback_prompt(task, user_answer, topic),
    )

    return response.text


def reset_session() -> None:
    for key in [
        "tasks",
        "current_task_index",
        "selected_topic_id",
        "selected_repetition_day",
        "last_feedback",
        "user_answer",
    ]:
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
st.write("Расписание повторений по Эббингаузу + задачи по одной + проверка через Gemini.")

with st.sidebar:
    st.header("Настройки")

    today_value = st.date_input(
        "Дата для расчёта повторений",
        value=date.today(),
        help="Можно поставить другую дату, чтобы проверить будущие или прошлые повторения.",
    )

    if st.button("Сбросить текущую сессию"):
        reset_session()
        st.rerun()

    st.markdown("---")
    st.caption("Дни повторения: 1, 3, 7, 14, 30.")

today_repetitions = get_today_repetitions(today_value)

st.header("Сегодня")

if not today_repetitions:
    st.info("На выбранную дату нет тем для повторения.")

    with st.expander("Показать все активные темы"):
        for topic in TOPICS:
            if topic.get("status") != "active":
                continue

            learned_date = parse_date(topic["learned_date"])
            days_passed = (today_value - learned_date).days
            upcoming_days = [
                repetition_day
                for repetition_day in REPETITION_DAYS
                if repetition_day >= days_passed
            ]

            next_day = upcoming_days[0] if upcoming_days else None

            if next_day is None:
                next_text = "все повторения пройдены"
            else:
                next_date = learned_date + timedelta(days=next_day)
                next_text = f"день {next_day}: {next_date.isoformat()}"

            st.write(
                f"**Блок {topic['block']}. {topic['title']}** — "
                f"изучено {topic['learned_date']}; следующее: {next_text}"
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
**Дата изучения:** {selected_topic["learned_date"]}  
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
                st.session_state["tasks"] = generate_tasks(
                    selected_topic,
                    selected_repetition_day,
                )
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
