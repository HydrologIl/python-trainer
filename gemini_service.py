import json
import random
import time
from typing import Any

import streamlit as st
from google import genai



# Генерация задач требует более сильной модели.
TASK_GENERATION_MODELS = [
    "gemini-2.5-pro",
    "gemini-2.5-flash",
]

# Проверка ответов обычно проще, поэтому используем модель дешевле/быстрее.
FEEDBACK_MODELS = [
    "gemini-2.5-flash",
    "gemini-2.5-pro",
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


def truncate_text(text: str, max_chars: int = 8000) -> str:
    text = normalize_cell(text)
    if len(text) <= max_chars:
        return text
    return text[:max_chars] + "\n...[текст обрезан по лимиту]"


def format_list_field(value: Any) -> str:
    text = normalize_cell(value)
    return text if text else "Не указано."


def format_topic_contract(topic: dict[str, Any]) -> str:
    """Build the curriculum contract from the new Market Track topic fields.

    The old app mainly used stage/block/title/description. The new Google Sheet
    has explicit boundaries: required_core, frequent_constructs, common_mistakes,
    do_not_touch and readiness_criteria. These fields should govern generation.
    """
    stage_label = topic.get("stage_title") or topic.get("stage") or "Не указан"
    stage_id = topic.get("stage_id") or ""
    stage_block_number = topic.get("stage_block_number") or topic.get("block") or ""
    global_order = topic.get("global_order") or topic.get("block") or ""

    return f"""
Учебный контракт текущего блока:
- curriculum_version: {topic.get("curriculum_version", "legacy")}
- stage_id: {stage_id}
- stage: {stage_label}
- stage_block_number: {stage_block_number}
- global_order: {global_order}
- topic_id: {topic.get("id", "")}
- title: {topic.get("title", "")}
- priority: {topic.get("priority", "")}
- recommended_duration: {topic.get("recommended_duration", "")}

Цель блока:
{format_list_field(topic.get("goal") or topic.get("description"))}

Обязательное ядро. Это разрешённые и ожидаемые инструменты для задач текущего блока:
{format_list_field(topic.get("required_core"))}

Частотные конструкции. На этих паттернах удобно строить задачи:
{format_list_field(topic.get("frequent_constructs"))}

Типовые ошибки. Желательно специально тренировать их распознавание и исправление:
{format_list_field(topic.get("common_mistakes"))}

Пока не трогать. Эти инструменты и темы запрещены для генерации задач по этому блоку:
{format_list_field(topic.get("do_not_touch"))}

Критерий готовности:
{format_list_field(topic.get("readiness_criteria"))}
"""


def format_known_blocks_context(topic: dict[str, Any]) -> str:
    known_blocks = topic.get("known_blocks", [])
    if not known_blocks:
        return "В Google Sheets нет явного списка пройденных блоков. Ориентируйся только на текущий учебный контракт."

    return ", ".join(str(block) for block in known_blocks)


def format_generation_guardrails(topic: dict[str, Any]) -> str:
    return f"""
Главное правило уровня:
- Генерируй задачи в зоне ближайшего развития: чуть сложнее примеров из блока, но без новых непройденных инструментов.
- Усложняй логику только внутри обязательного ядра текущего и уже пройденных блоков.
- Раздел «Пока не трогать» имеет приоритет выше режима сложности, датасета и реалистичности бизнес-кейса.
- Если реалистичный кейс требует запрещённого инструмента, упрости кейс или замени инструмент.
- Не используй pandas до блоков pandas, SQL до блоков SQL, API до блоков API, try/except до блоков обработки ошибок, если они указаны как запрещённые или ещё не являются частью текущего блока.
- Не добавляй list/dict/set/циклы/файлы/классы/regex/type hints только ради разнообразия, если их нет в обязательном ядре текущего или уже пройденных блоков.
- Для M0 ранних блоков особенно строго соблюдай границы: функции и условия должны тренироваться через параметры, return и простые значения, а не через будущие коллекции, если коллекции ещё не пройдены.
"""


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



def format_difficulty_profile(profile: str | None) -> str:
    profile = normalize_cell(profile or "balanced")

    profiles = {
        "balanced": """
Режим сложности: сбалансированный.
- 30% задач — простые разогревочные;
- 50% задач — рабочие задачи уровня тестового задания для аналитика;
- 20% задач — чуть сложнее базового уровня, но без выхода за изученные конструкции.
""",
        "harder": """
Режим сложности: сложнее обычного.
- Не делай однотипные задачи на один if/else.
- Добавляй небольшие комбинации: функция + условие, функция + цикл, список + фильтрация, словарь + подсчёт, обработка граничного случая.
- Задачи должны оставаться решаемыми изученными средствами, но требовать подумать над структурой решения.
- Избегай больших проектов: это короткие задачи, но с более плотной логикой.
""",
        "interview": """
Режим сложности: ближе к Python-тестам для аналитика данных.
- Формулируй задачи как маленькие рабочие кейсы: метрики, клиенты, заказы, HR, маркетинг, финансы.
- Включай функции, возврат значений, преобразование коллекций, проверку граничных случаев.
- Не усложняй за пределы уже изученных тем, но убирай учебную механистичность.
""",
    }

    return profiles.get(profile, profiles["balanced"])


def format_topic_materials_context(materials_context: str | None) -> str:
    materials_context = normalize_cell(materials_context)

    if not materials_context:
        return "Дополнительные материалы по теме не переданы."

    max_chars = 12000
    if len(materials_context) > max_chars:
        materials_context = materials_context[:max_chars] + "\n...[материалы обрезаны по лимиту]"

    return f"""
Дополнительные материалы, по которым студент изучал эту тему.
Используй их как источник терминов, объяснений, типов задач и уровня сложности.
Не копируй текст дословно, а генерируй новые задачи по тем же понятиям и паттернам.

{materials_context}
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
    difficulty_profile: str = "balanced",
    topic_materials_context: str = "",
) -> str:
    topic_contract = format_topic_contract(topic)
    known_blocks = format_known_blocks_context(topic)
    dataset_context = format_dataset_context(dataset)
    difficulty_context = format_difficulty_profile(difficulty_profile)
    materials_context = format_topic_materials_context(topic_materials_context)
    guardrails = format_generation_guardrails(topic)

    return f"""
Ты — эксперт по Python для анализа данных и опытный преподаватель.

Твоя задача — сгенерировать учебные задачи для повторения по кривой Эббингауза.

Теперь источник правды — не старый curriculum.py, а строка текущей темы из Google Sheets.
Используй учебный контракт ниже как главный ограничитель содержания, сложности и допустимых инструментов.

{topic_contract}

Студент уже прошёл блоки по глобальной нумерации:
{known_blocks}

День повторения:
{repetition_day}

{guardrails}

Журнал жалоб пользователя на ранее сгенерированные задачи. Это дефекты генерации, а не ошибки пользователя.
Используй этот журнал как анти-примеры и не повторяй такие проблемы:
{task_feedback_context}

Контекст датасета:
{dataset_context}

Режим сложности:
{difficulty_context}

Материалы по теме:
{materials_context}

Сгенерируй ровно 40 задач:
- 10 задач на исправление ошибок;
- 10 задач формата "что выведет код?";
- 20 задач на написание кода.

Требования к содержанию:
- задачи должны проверять именно текущую тему;
- для решения должны требоваться только знания из обязательного ядра текущего и уже пройденных блоков;
- запрещено использовать конструкции из поля «Пока не трогать»;
- если текущий блок ранний, не забегай вперёд ради реалистичности;
- если тема не является итоговым проектом, не превращай обычную тренировку в большой проект;
- не давай подсказок в условиях;
- не давай решений;
- не добавляй комментарии-подсказки в код;
- задачи должны быть уникальными по данным, формулировке и требуемому действию;
- не генерируй 20 задач одного шаблона “input → if/else → print”;
- используй input() только если тема явно про ввод с клавиатуры; в остальных случаях чаще давай готовые переменные или параметры функции;
- не требуй print там, где естественнее вернуть значение из функции;
- если return входит в обязательное ядро текущего или предыдущих блоков, чаще проси вернуть значение через return;
- если списки/словари/pandas/SQL/API не входят в обязательное ядро текущего или предыдущих блоков, не используй их;
- где уместно и не нарушает границы темы, используй контекст реальных данных: продажи, маркетинг, HR, финансы, клиенты;
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
    topic_contract = format_topic_contract(topic)

    return f"""
Ты проверяешь решение учебной задачи по Python.

{topic_contract}

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
- проверяй решение в рамках учебного контракта текущего блока;
- если пользователь решил задачу более продвинутым способом, не ругай его автоматически, но отметь, если способ выходит за рамки текущего блока;
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
    difficulty_profile: str = "balanced",
    topic_materials_context: str = "",
) -> list[dict[str, Any]]:
    response_text = call_gemini_with_retry(
        build_task_generation_prompt(
            topic,
            repetition_day,
            task_feedback_context,
            dataset=dataset,
            difficulty_profile=difficulty_profile,
            topic_materials_context=topic_materials_context,
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
    known_blocks = format_known_blocks_context(topic)
    examples_text = "\n".join(f"- {example}" for example in mistake_examples) or "Примеров нет."
    dataset_context = format_dataset_context(dataset)
    topic_contract = format_topic_contract(topic)
    guardrails = format_generation_guardrails(topic)

    return f"""
Ты — эксперт по Python для анализа данных и опытный преподаватель.

Нужно сгенерировать короткую тренировку на слабое место студента.

{topic_contract}

Студент уже прошёл блоки по глобальной нумерации:
{known_blocks}

{guardrails}

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
- для решения должны требоваться только знания из обязательного ядра текущего и уже пройденных блоков;
- запрещено использовать конструкции из поля «Пока не трогать»;
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



def build_task_hint_prompt(
    task: dict[str, Any],
    topic: dict[str, Any],
    user_answer: str = "",
    hint_mode: str = "hint",
) -> str:
    mode = normalize_cell(hint_mode) or "hint"
    code_part = task.get("code", "")
    topic_contract = format_topic_contract(topic)

    if mode == "consultation":
        help_instruction = """
Дай короткую консультацию по подходу к решению:
- какие понятия из темы здесь нужны;
- как разложить задачу на 2–4 шага;
- на что обратить внимание;
- не давай финальный готовый код, если пользователь не прислал почти готовое решение.
"""
    else:
        help_instruction = """
Дай одну полезную подсказку:
- не раскрывай полное решение;
- не пиши финальный код целиком;
- подтолкни к следующему шагу.
"""

    return f"""
Ты помогаешь студенту решить учебную задачу по Python.

{topic_contract}

Тип задачи:
{task.get("type")}

Условие задачи:
{task.get("task")}

Код из условия, если есть:
```python
{code_part}
```

Текущий ответ пользователя, если он уже что-то написал:
```python
{user_answer}
```

{help_instruction}

Пиши на русском, коротко и по делу. Не используй инструменты из поля «Пока не трогать», если они не нужны для объяснения запрета.
"""


def get_task_hint(
    task: dict[str, Any],
    topic: dict[str, Any],
    user_answer: str = "",
    hint_mode: str = "hint",
) -> str:
    return call_gemini_with_retry(
        build_task_hint_prompt(
            task=task,
            topic=topic,
            user_answer=user_answer,
            hint_mode=hint_mode,
        ),
        models=FEEDBACK_MODELS,
    )


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
