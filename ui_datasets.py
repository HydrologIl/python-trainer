from typing import Any

import streamlit as st

from sheets import get_active_datasets, load_datasets


def get_dataset_selector(
    label: str = "Датасет для контекста задач",
    key: str = "dataset_selector",
) -> dict[str, Any] | None:
    try:
        datasets = get_active_datasets()
    except Exception as e:
        st.warning("Не удалось прочитать лист datasets. Генерация будет без датасета.")
        st.code(str(e))
        return None

    if not datasets:
        st.info("Активных датасетов нет. Генерация будет без датасета.")
        return None

    options = [None] + datasets

    selected_dataset = st.selectbox(
        label,
        options,
        format_func=lambda dataset: (
            "Без датасета"
            if dataset is None
            else f"{dataset['name']} ({dataset['domain']})"
        ),
        key=key,
    )

    if selected_dataset:
        with st.expander("Контекст выбранного датасета"):
            st.write(f"**Описание:** {selected_dataset.get('description')}")
            st.write(f"**Таблицы:** {selected_dataset.get('tables')}")
            st.write(f"**Колонки:** {selected_dataset.get('columns')}")
            st.write(f"**Пример строки:** {selected_dataset.get('example_rows')}")
            st.write(f"**Подходит для:** {selected_dataset.get('best_for_topics')}")

    return selected_dataset


def render_datasets_tab() -> None:
    st.header("Датасеты")

    st.write(
        "Каталог датасетов читается из Google Sheets. "
        "Пока приложение использует описание датасета как контекст для Gemini, "
        "без загрузки реальных CSV."
    )

    try:
        datasets = load_datasets()
    except Exception as e:
        st.error("Не удалось прочитать лист datasets.")
        st.code(str(e))
        return

    if not datasets:
        st.info("В листе datasets пока нет строк.")
        return

    active_count = len([dataset for dataset in datasets if dataset.get("status") == "active"])
    st.caption(f"Всего датасетов: {len(datasets)} · активных: {active_count}")

    for dataset in datasets:
        status = dataset.get("status", "")
        st.markdown(f"### {dataset.get('name') or dataset.get('dataset_id')}")
        st.caption(
            f"{dataset.get('domain')} · {dataset.get('difficulty')} · "
            f"status: `{status}`"
        )
        st.write(dataset.get("description"))

        with st.expander("Схема и примеры"):
            st.write(f"**dataset_id:** `{dataset.get('dataset_id')}`")
            st.write(f"**tables:** {dataset.get('tables')}")
            st.write(f"**columns:** {dataset.get('columns')}")
            st.write(f"**example_rows:** {dataset.get('example_rows')}")
            st.write(f"**best_for_topics:** {dataset.get('best_for_topics')}")
            st.write(f"**source:** {dataset.get('source')}")
