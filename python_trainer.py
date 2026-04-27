import streamlit as st
from google import genai

TASKS = [
    {
        "title": "Задача 1: сумма чисел",
        "description": """
Напиши функцию `sum_numbers(numbers)`, которая принимает список чисел и возвращает их сумму.

Пример:
sum_numbers([1, 2, 3])  # 6
"""
    },
    {
        "title": "Задача 2: чётные числа",
        "description": """
Напиши функцию `get_even(numbers)`, которая возвращает только чётные числа.

Пример:
get_even([1, 2, 3, 4])  # [2, 4]
"""
    },
    {
        "title": "Задача 3: переворот строки",
        "description": """
Напиши функцию `reverse_text(text)`, которая возвращает строку в обратном порядке.

Пример:
reverse_text('hello')  # 'olleh'
"""
    }
]

STARTER_CODE = {
    "Задача 1: сумма чисел": "def sum_numbers(numbers):\n    pass",
    "Задача 2: чётные числа": "def get_even(numbers):\n    pass",
    "Задача 3: переворот строки": "def reverse_text(text):\n    pass",
}


def build_prompt(task_description: str, user_code: str) -> str:
    return f"""
Ты проверяешь решение учебной задачи по Python.

Твоя роль:
- не просто сказать "правильно/неправильно";
- объяснить, что работает, а что нет;
- дать подсказку, если решение ошибочное;
- не переписывать сразу весь код, если пользователь близок к решению;
- писать понятно и коротко, на русском языке.

Задача:
{task_description}

Код пользователя:
```python
{user_code}
```

Ответь в формате:
1. Вердикт: решение корректное / частично корректное / некорректное.
2. Что хорошо.
3. Что нужно исправить.
4. Мини-подсказка.
"""


def ask_gemini(task_description: str, user_code: str) -> str:
    api_key = st.secrets.get("GEMINI_API_KEY")

    if not api_key:
        return (
            "Не найден GEMINI_API_KEY в Streamlit secrets.\n\n"
            "Добавь секрет в настройках приложения:\n"
            "GEMINI_API_KEY = \"твой_ключ\""
        )

    client = genai.Client(api_key=api_key)

    response = client.models.generate_content(
        model="gemini-2.5-flash",
        contents=build_prompt(task_description, user_code),
    )

    return response.text


st.set_page_config(page_title="Python Trainer", page_icon="🐍")

st.title("Python Trainer")
st.write("Выбери задачу, напиши код и отправь его на проверку в Gemini.")

task_index = st.selectbox(
    "Выбери задачу",
    range(len(TASKS)),
    format_func=lambda i: TASKS[i]["title"]
)

task = TASKS[task_index]

st.subheader(task["title"])
st.markdown(task["description"])

default_code = STARTER_CODE.get(task["title"], "")

user_code = st.text_area(
    "Твой код",
    value=default_code,
    height=260
)

if st.button("Проверить"):
    if not user_code.strip():
        st.warning("Сначала вставь или напиши код.")
    else:
        with st.spinner("Gemini проверяет решение..."):
            try:
                feedback = ask_gemini(task["description"], user_code)
                st.markdown("### Ответ Gemini")
                st.markdown(feedback)
            except Exception as e:
                st.error("Не удалось получить ответ от Gemini.")
                st.code(str(e))
