import json
import random
import time
from typing import Any

import streamlit as st
from google import genai

from curriculum import GENERAL_CURRICULUM, STAGE_0_CURRICULUM


# Генерация задач требует более сильной модели.
TASK_GENERATION_MODELS = [
    "gemini-2.5-pro",
    "gemini-2.5-flash",
]

# Проверка ответов обычно проще, поэтому используем модель дешевле/быстрее.
FEEDBACK_MODELS = [
    "gemini-2.5-flash-lite",
    "gemini-2.5-flash",
]

# Для отображения в sidebar старого ui.py.
FALLBACK_MODELS = [
    f"generation: {TASK_GENERATION_MODELS[0]}",
    f"feedback: {FEEDBACK_MODELS[0]}",
]


def normalize_cell(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()




def format_dataset_context(dataset: dict[str, Any] | None) -> str:
    if not dataset:
        return "Датасет не выбран. Генерируй задачи на простых реалистичных примерах."

    return f"""
Выбранный датасет для контекста задач:
- dataset_id: {dataset.get("dataset_id", "")}
- name: {dataset.get("name", "")}
- domain: {dataset.get("domain", "")}
- description: {dataset.get("description", "")}
- tables: {dataset.get("tables", "")}
- columns: {dataset.get("columns", "")}
- example_rows: {dataset.get("example_rows", "")}
- best_for_topics: {dataset.get("best_for_topics", "")}
- difficulty: {dataset.get("difficulty", "")}
- source: {dataset.get("source", "")}

Используй этот датасет как реалистичный бизнес-контекст для задач.
Не требуй чтения настоящего CSV, если задача рассчитана на ранние блоки Python.
Можно использовать маленькие списки, словари и фрагменты данных, имитирующие строки этого датасета.
Если тема уже связана с pandas/файлами, можно формулировать задачи как работу с таблицей или фрагментом CSV.
"""


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


def get_api_key() -> str | None:
    return st.secrets.get("GEMINI_API_KEY")


def get_gemini_client() -> genai.Client | None:
    api_key = get_api_key()

    if not api_key:
        return None

    return genai.Client(api_key=api_key)


def is_retryable_error(message: str) -> bool:
    lowered = message.lower()

    return (
        "503" in message
        or "unavailable" in lowered
        or "overloaded" in lowered
        or "high demand" in lowered
        or "retry" in lowered
    )


def is_quota_error(message: str) -> bool:
    lowered = message.lower()

    return (
        "429" in message
        or "resource_exhausted" in lowered
        or "quota" in lowered
        or "rate limit" in lowered
    )


def call_gemini_with_retry(prompt: str, models: list[str]) -> str:
    client = get_gemini_client()

    if client is None:
        raise RuntimeError(
            "Не найден GEMINI_API_KEY в Streamlit secrets. "
            "Добавь его в настройках приложения."
        )

    last_error = None

    for model in models:
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

                if is_quota_error(message):
                    break

                if not is_retryable_error(message):
                    raise

                sleep_seconds = min(12, (2 ** attempt) + random.uniform(0, 1.5))
                time.sleep(sleep_seconds)

    raise RuntimeError(
        "Gemini не смог обработать запрос доступными моделями. "
        "Возможные причины: квота, rate limit, перегрузка модели или billing. "
        f"Модели: {models}. Последняя ошибка: {last_error}"
    )


def build_task_generation_prompt(
    topic: dict[str, Any],
    repetition_day: int,
    task_feedback_context: str = "Пока нет сохранённых жалоб на задачи.",
    dataset: dict[str, Any] | None = None,
) -> str:
    known_blocks = ", ".join(str(block) for block in topic.get("known_blocks", []))
    dataset_context = format_dataset_context(dataset)

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

Журнал жалоб пользователя на ранее сгенерированные задачи. Это дефекты генерации, а не ошибки пользователя.
Используй этот журнал как анти-примеры и не повторяй такие проблемы:
{task_feedback_context}

Контекст датасета:
{dataset_context}

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
- язык — русский;
- для задач типа "debug" в коде ОБЯЗАНА быть реальная ошибка;
- для задач типа "debug" условие НЕ ДОЛЖНО говорить, что код неправильный, если код уже корректен;
- для задач типа "debug" перед выдачей задачи мысленно проверь, что ошибка действительно существует;
- для задач типа "output_prediction" код должен быть корректным и исполняемым, если задача не просит найти ошибку.

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


def build_feedback_prompt(
    task: dict[str, Any],
    user_answer: str,
    topic: dict[str, Any],
) -> str:
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


def generate_tasks(
    topic: dict[str, Any],
    repetition_day: int,
    task_feedback_context: str = "Пока нет сохранённых жалоб на задачи.",
    dataset: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    response_text = call_gemini_with_retry(
        build_task_generation_prompt(
            topic,
            repetition_day,
            task_feedback_context,
            dataset=dataset,
        ),
        models=TASK_GENERATION_MODELS,
    )
    return extract_json_from_gemini(response_text)



def build_weak_spot_generation_prompt(
    topic: dict[str, Any],
    mistake_type: str,
    mistake_examples: list[str],
    task_count: int,
    difficulty: str,
    dataset: dict[str, Any] | None = None,
) -> str:
    known_blocks = ", ".join(str(block) for block in topic.get("known_blocks", []))
    examples_text = "\n".join(f"- {example}" for example in mistake_examples) or "Примеров нет."
    dataset_context = format_dataset_context(dataset)

    return f"""
Ты — эксперт по Python для анализа данных и опытный преподаватель.

Нужно сгенерировать короткую тренировку на слабое место студента.

Текущая тема:
{topic["stage"]}, блок {topic["block"]}: {topic["title"]}

Описание темы:
{topic["description"]}

Студент уже прошёл блоки:
{known_blocks}

Слабое место:
{mistake_type}

Примеры прошлых ошибок:
{examples_text}

Контекст датасета для задач на слабое место:
{dataset_context}

Сгенерируй ровно {task_count} задач.

Требования:
- задачи должны тренировать именно слабое место;
- задачи должны быть в рамках текущей темы;
- для решения должны требоваться только знания из уже пройденных блоков;
- не давай решений;
- не давай подсказок в условии;
- язык русский;
- сложность: {difficulty};
- смешай форматы задач:
  - исправление ошибок;
  - что выведет код;
  - написание кода;
- для debug-задач в коде должна быть реальная ошибка;
- output_prediction должен содержать корректный исполняемый код.

Верни строго валидный JSON без markdown-блока и без пояснений.

Формат JSON:
[
  {{
    "id": 1,
    "type": "debug",
    "difficulty": "{difficulty}",
    "task": "Текст условия",
    "code": "код, если он нужен для задачи"
  }}
]
"""


def generate_weak_spot_tasks(
    topic: dict[str, Any],
    mistake_type: str,
    mistake_examples: list[str],
    task_count: int = 10,
    difficulty: str = "начальный",
    dataset: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    response_text = call_gemini_with_retry(
        build_weak_spot_generation_prompt(
            topic=topic,
            mistake_type=mistake_type,
            mistake_examples=mistake_examples,
            task_count=task_count,
            difficulty=difficulty,
            dataset=dataset,
        ),
        models=TASK_GENERATION_MODELS,
    )
    return extract_json_from_gemini(response_text)



def get_feedback_json(
    task: dict[str, Any],
    user_answer: str,
    topic: dict[str, Any],
) -> dict[str, str]:
    response_text = call_gemini_with_retry(
        build_feedback_prompt(task, user_answer, topic),
        models=FEEDBACK_MODELS,
    )
    return extract_feedback_json(response_text)
