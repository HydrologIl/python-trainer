

import streamlit as st
import traceback

TASKS = [
    {
        "title": "Задача 1: сумма чисел",
        "description": """
Напиши функцию `sum_numbers(numbers)`, которая принимает список чисел и возвращает их сумму.

Пример:
sum_numbers([1, 2, 3])  # 6
""",
        "tests": [
            ("sum_numbers([1, 2, 3])", 6),
            ("sum_numbers([])", 0),
            ("sum_numbers([-1, 5, 10])", 14),
        ],
        "starter": "def sum_numbers(numbers):\n    pass"
    },
    {
        "title": "Задача 2: чётные числа",
        "description": """
Напиши функцию get_even(numbers), которая возвращает только чётные числа.

Пример:
get_even([1, 2, 3, 4])  # [2, 4]
""",
        "tests": [
            ("get_even([1, 2, 3, 4])", [2, 4]),
            ("get_even([1, 3, 5])", []),
            ("get_even([0, -2, 7])", [0, -2]),
        ],
        "starter": "def get_even(numbers):\n    pass"
    },
    {
        "title": "Задача 3: переворот строки",
        "description": """
Напиши функцию reverse_text(text).

Пример:
reverse_text('hello')  # 'olleh'
""",
        "tests": [
            ("reverse_text('hello')", "olleh"),
            ("reverse_text('')", ""),
            ("reverse_text('Python')", "nohtyP"),
        ],
        "starter": "def reverse_text(text):\n    pass"
    }
]

st.title("Python Trainer")

task_index = st.selectbox(
    "Выбери задачу",
    range(len(TASKS)),
    format_func=lambda i: TASKS[i]["title"]
)

task = TASKS[task_index]

st.subheader(task["title"])
st.markdown(task["description"])

user_code = st.text_area(
    "Твой код",
    value=task["starter"],
    height=250
)

if st.button("Проверить"):
    local_env = {}

    try:
        exec(user_code, {}, local_env)

        passed = 0

        for test_code, expected in task["tests"]:
            result = eval(test_code, {}, local_env)
            if result == expected:
                st.success(f"{test_code} → OK")
                passed += 1
            else:
                st.error(f"{test_code} → {result}, ожидалось {expected}")

        st.write(f"Пройдено: {passed}/{len(task['tests'])}")

    except Exception:
        st.error(traceback.format_exc())
