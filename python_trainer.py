import json
import random
import time
from datetime import date, datetime, timedelta
from typing import Any

import streamlit as st
from google import genai

from curriculum import GENERAL_CURRICULUM, STAGE_0_CURRICULUM, TOPICS


REPETITION_DAYS = [1, 3, 7, 14, 30]

# Более дешёвая/быстрая модель по умолчанию.
# Если она перегружена, приложение попробует fallback-модели.
DEFAULT_MODEL = "gemini-2.5-flash-lite"
FALLBACK_MODELS = [
    "gemini-2.5-flash-lite",
    "gemini-2.5-flash",
]


def parse_date(value: str) -> date:
    return datetime.strptime(value, "%Y-%m-%d").date()


def topic_state_defaults() -> dict[str, dict[str, str]]:
    return {
        topic["id"]: {
            "learned_date": topic.get("learned_date", ""),
            "status": topic.get("status", "planned"),
        }
        for topic in TOPICS
    }


def init_topic_state() -> None:
    if "topic_state" not in st.session_state:
        st.session_state["topic_state"] = topic_state_defaults()


def get_topic_learned_date(topic: dict[str, Any]) -> str:
    return st.session_state["topic_state"].get(topic["id"], {}).get("learned_date", "")


def get_topic_status(topic: dict[str, Any]) -> str:
    return st.session_state["topic_state"].get(topic["id"], {}).get("status", "planned")


def set_topic_state(topic_id: str, learned_date: str, status: str) -> None:
    st.session_state["topic_state"][topic_id] = {
        "learned_date": learned_date,
        "status": status,
    }


def get_repetition_info(topic: dict[str, Any], today: date) -> dict[str, Any] | None:
    status = get_topic_status(topic)
    learned_date_value = get_topic_learned_date(topic)

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


def get_today_repetitions(today: date) -> list[dict[str, Any]]:
    repetitions = []

    for topic in TOPICS:
        repetition_info = get_repetition_info(topic, today)
        if repetition_info:
            repetitions.append(repetition_info)

    return repetitions


def get_next_repetition(topic: dict[str, Any], today: date) -> str:
    learned_date_value = get_topic_learned_date(topic)
    status = get_topic_status(topic)

    if status == "planned":
        return "тема ещё не отмечена как пройденная"

    if status == "completed":
        return "тема закрыта"

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
        "Попробуй позже или смени модель. Последняя ошибка: "
        f"{last_error}"
    )


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
    response_text = call_gemini_with_retry(
        build_task_generation_prompt(topic, repetition_day),
        models=FALLBACK_MODELS,
    )
    return extract_json_from_gemini(response_text)


def get_feedback(task: dict[str, Any], user_answer: str, topic: dict[str, Any]) -> str:
    return call_gemini_with_retry(
        build_feedback_prompt(task, user_answer, topic),
        models=FALLBACK_MODELS,
    )


def reset_session() -> None:
    for key in [
        "tasks",
        "current_task_index",
        "selected_topic_id",
        "selected_repetition_day",
        "last_feedback",
        "user_answer",
        "answer_input",
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

init_topic_state()

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
    st.caption(f"Модели Gemini: {', '.join(FALLBACK_MODELS)}")

tab_today, tab_plan = st.tabs(["Сегодня", "Учебный план"])

with tab_plan:
    st.header("Учебный план")

    st.info(
        "Здесь можно отметить тему как пройденную и указать дату изучения. "
        "Пока это хранится в текущей сессии Streamlit. После перезапуска приложения "
        "данные могут сброситься. Для постоянного хранения следующим этапом нужна база: "
        "Google Sheets, Supabase или другая."
    )

    selected_topic_for_edit = st.selectbox(
        "Тема",
        TOPICS,
        format_func=lambda topic: f"Блок {topic['block']}. {topic['title']}",
    )

    current_status = get_topic_status(selected_topic_for_edit)
    current_learned_date = get_topic_learned_date(selected_topic_for_edit)

    status = st.selectbox(
        "Статус",
        ["planned", "active", "completed"],
        index=["planned", "active", "completed"].index(current_status),
        format_func=lambda value: {
            "planned": "запланирована",
            "active": "пройдена, повторять",
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
            set_topic_state(
                selected_topic_for_edit["id"],
                learned_date_input.isoformat(),
                status,
            )
            reset_session()
            st.success("Сохранено для текущей сессии.")
            st.rerun()

    with col_b:
        if st.button("Отметить как пройденную сегодня"):
            set_topic_state(
                selected_topic_for_edit["id"],
                today_value.isoformat(),
                "active",
            )
            reset_session()
            st.success("Тема отмечена как пройденная сегодня.")
            st.rerun()

    st.subheader("Все темы")

    for topic in TOPICS:
        st.write(
            f"**Блок {topic['block']}. {topic['title']}** — "
            f"статус: `{get_topic_status(topic)}`, "
            f"дата изучения: `{get_topic_learned_date(topic) or 'не указана'}`, "
            f"следующее: {get_next_repetition(topic, today_value)}"
        )

    st.download_button(
        "Скачать текущие даты как JSON",
        data=json.dumps(st.session_state["topic_state"], ensure_ascii=False, indent=2),
        file_name="topic_state.json",
        mime="application/json",
    )

with tab_today:
    st.header("Сегодня")

    today_repetitions = get_today_repetitions(today_value)

    if not today_repetitions:
        st.info("На выбранную дату нет тем для повторения.")

        with st.expander("Показать все активные темы"):
            for topic in TOPICS:
                if get_topic_status(topic) != "active":
                    continue

                st.write(
                    f"**Блок {topic['block']}. {topic['title']}** — "
                    f"изучено {get_topic_learned_date(topic)}; "
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
**Дата изучения:** {get_topic_learned_date(selected_topic)}  
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
