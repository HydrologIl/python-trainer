from __future__ import annotations

import hmac
import json
import os
from datetime import date, datetime
from typing import Any, Mapping
from zoneinfo import ZoneInfo

import streamlit as st

from learning_app.ai import create_ai_provider
from learning_app.repository import LearningRepository, ReviewAssignment, Task
from learning_app.services import LearningService
from learning_app.training_profiles import (
    ANALYSIS_GROUP,
    CREATION_GROUP,
    DEFAULT_CUSTOM_CONFIG,
    FORMAT_LABELS,
    GROUP_LABELS,
    GROUP_ORDER,
    PROFILE_DESCRIPTIONS,
    PROFILE_KEYS,
    PROFILE_LABELS,
    THEORY_GROUP,
    build_task_plan,
    custom_config_errors,
    formats_for_group,
    normalize_custom_config,
    task_plan_summary,
)


CLOSED_TASK_STATUSES = {"correct", "abandoned", "bad_task"}


def _secret(name: str, default: str = "") -> str:
    try:
        value = st.secrets.get(name, default)
    except Exception:
        value = os.getenv(name, default)
    return str(value or default)


def require_private_access() -> None:
    expected = _secret("APP_PASSWORD")
    if not expected:
        st.sidebar.warning("APP_PASSWORD не задан: приложение не защищено паролем.")
        return
    if st.session_state.get("authenticated"):
        return

    st.title("Learning App")
    password = st.text_input("Пароль", type="password")
    if st.button("Войти"):
        if hmac.compare_digest(password, expected):
            st.session_state["authenticated"] = True
            st.rerun()
        st.error("Неверный пароль.")
    st.stop()


@st.cache_resource
def get_repository(database_url: str) -> LearningRepository:
    repository = LearningRepository(database_url=database_url)
    repository.create_schema()
    return repository


@st.cache_resource
def get_service(
    database_url: str,
    provider_name: str,
    provider_model: str,
    timezone_name: str,
) -> LearningService:
    repository = get_repository(database_url)
    secrets: dict[str, str] = {
        "AI_PROVIDER": provider_name,
        "XAI_API_KEY": _secret("XAI_API_KEY"),
        "GEMINI_API_KEY": _secret("GEMINI_API_KEY"),
        "XAI_MODEL": provider_model if provider_name == "xai" else _secret("XAI_MODEL", "grok-4.7"),
        "GEMINI_MODEL": (
            provider_model
            if provider_name == "gemini"
            else _secret("GEMINI_MODEL", "gemini-2.5-pro")
        ),
    }
    return LearningService(
        repository,
        create_ai_provider(provider_name, secrets),
        timezone_name=timezone_name,
    )


def _provider_settings() -> tuple[str, str]:
    provider = _secret("AI_PROVIDER", "xai").lower()
    default_model = "grok-4.7" if provider == "xai" else "gemini-2.5-pro"
    key = "XAI_MODEL" if provider == "xai" else "GEMINI_MODEL"
    return provider, _secret(key, default_model)


def _timezone_name() -> str:
    return _secret("APP_TIMEZONE", "Asia/Yerevan")


def _today_in_app_timezone() -> date:
    try:
        return datetime.now(ZoneInfo(_timezone_name())).date()
    except Exception:
        return date.today()


def run_universal_app() -> None:
    st.set_page_config(page_title="Learning App", page_icon="🧠", layout="wide")
    require_private_access()

    database_url = _secret("DATABASE_URL", "sqlite:///learning_app.db")
    provider_name, provider_model = _provider_settings()
    repository = get_repository(database_url)

    st.title("Learning App")
    st.caption("Курсы, интервальные повторения и адаптивные тренировки")
    with st.sidebar:
        today = st.date_input("Дата", value=_today_in_app_timezone())
        st.caption(f"AI: {provider_name} · {provider_model}")
        if database_url.startswith("sqlite"):
            st.warning("SQLite подходит для локальной разработки. Для Streamlit Cloud задай PostgreSQL DATABASE_URL.")

    section = st.radio(
        "Раздел",
        ["Сегодня", "Курсы", "Прогресс", "Миграция"],
        horizontal=True,
        label_visibility="collapsed",
        key="main_section",
    )
    if section == "Сегодня":
        render_today(repository, database_url, provider_name, provider_model, today)
    elif section == "Курсы":
        render_courses(repository, database_url, provider_name, provider_model)
    elif section == "Прогресс":
        render_progress(repository)
    else:
        render_migration(repository)


def _service(database_url: str, provider_name: str, provider_model: str) -> LearningService:
    try:
        return get_service(
            database_url,
            provider_name,
            provider_model,
            _timezone_name(),
        )
    except Exception as exc:
        st.error("AI-провайдер пока не настроен.")
        st.code(str(exc))
        st.stop()


def _profile_option_label(profile_key: str) -> str:
    return PROFILE_LABELS.get(profile_key, profile_key)


def _custom_profile_editor(
    key_prefix: str,
    stored_config: dict[str, Any] | None,
) -> dict[str, Any]:
    config = normalize_custom_config(stored_config or DEFAULT_CUSTOM_CONFIG)
    weights = config["group_weights"]
    creation = int(
        st.number_input(
            "Создание, %",
            min_value=0,
            max_value=100,
            value=int(weights[CREATION_GROUP]),
            key=f"{key_prefix}_creation",
        )
    )
    analysis = int(
        st.number_input(
            "Анализ, %",
            min_value=0,
            max_value=100,
            value=int(weights[ANALYSIS_GROUP]),
            key=f"{key_prefix}_analysis",
        )
    )
    theory = max(0, 100 - creation - analysis)
    st.caption(f"Теория: {theory}% · всего: {creation + analysis + theory}%")

    selected_formats: list[str] = []
    with st.expander("Разрешённые форматы"):
        for group in GROUP_ORDER:
            group_formats = formats_for_group(group)
            defaults = [
                task_format
                for task_format in config["allowed_formats"]
                if task_format in group_formats
            ]
            selected_formats.extend(
                st.multiselect(
                    GROUP_LABELS[group],
                    group_formats,
                    default=defaults,
                    format_func=lambda value: FORMAT_LABELS[value],
                    key=f"{key_prefix}_formats_{group}",
                )
            )

    return {
        "group_weights": {
            CREATION_GROUP: creation,
            ANALYSIS_GROUP: analysis,
            THEORY_GROUP: theory,
        },
        "allowed_formats": selected_formats,
    }


def _render_course_profile_settings(repository: LearningRepository, course: Any) -> None:
    setting = repository.get_training_profile_setting("course", course.id)
    fallback_key = "python_practice" if course.legacy_id == "legacy:python" else "auto"
    current_key = setting.profile_key if setting else fallback_key
    current_config = dict(setting.config or {}) if setting else {}

    with st.expander("Профиль тренировок курса"):
        selected = st.selectbox(
            "Профиль по умолчанию",
            PROFILE_KEYS,
            index=PROFILE_KEYS.index(current_key) if current_key in PROFILE_KEYS else 0,
            format_func=_profile_option_label,
            key=f"course_profile_{course.id}",
        )
        st.caption(PROFILE_DESCRIPTIONS[selected])
        config = (
            _custom_profile_editor(f"course_custom_{course.id}", current_config)
            if selected == "custom"
            else {}
        )
        errors = custom_config_errors(config) if selected == "custom" else []
        for error in errors:
            st.warning(error)
        if st.button(
            "Сохранить профиль курса",
            disabled=bool(errors),
            key=f"save_course_profile_{course.id}",
        ):
            repository.set_training_profile("course", course.id, selected, config)
            st.success("Профиль курса сохранён.")
            st.rerun()


def _render_module_profile_settings(
    repository: LearningRepository,
    module: Any,
) -> None:
    setting = repository.get_training_profile_setting("module", module.id)
    options = ("inherit",) + PROFILE_KEYS
    current_key = setting.profile_key if setting else "inherit"
    current_config = dict(setting.config or {}) if setting else {}
    course = repository.get_course(module.course_id)
    course_setting = repository.get_training_profile_setting("course", module.course_id)
    inherited_key = (
        course_setting.profile_key
        if course_setting is not None
        else "python_practice"
        if course is not None and course.legacy_id == "legacy:python"
        else "auto"
    )

    with st.expander("Профиль тренировок модуля"):
        selected = st.selectbox(
            "Настройка модуля",
            options,
            index=options.index(current_key) if current_key in options else 0,
            format_func=lambda value: (
                f"Использовать профиль курса ({PROFILE_LABELS[inherited_key]})"
                if value == "inherit"
                else _profile_option_label(value)
            ),
            key=f"module_profile_{module.id}",
        )
        if selected != "inherit":
            st.caption(PROFILE_DESCRIPTIONS[selected])
        config = (
            _custom_profile_editor(f"module_custom_{module.id}", current_config)
            if selected == "custom"
            else {}
        )
        errors = custom_config_errors(config) if selected == "custom" else []
        for error in errors:
            st.warning(error)
        if st.button(
            "Сохранить профиль модуля",
            disabled=bool(errors),
            key=f"save_module_profile_{module.id}",
        ):
            if selected == "inherit":
                repository.clear_training_profile("module", module.id)
            else:
                repository.set_training_profile("module", module.id, selected, config)
            st.success("Профиль модуля сохранён.")
            st.rerun()


def render_courses(
    repository: LearningRepository,
    database_url: str,
    provider_name: str,
    provider_model: str,
) -> None:
    st.header("Курсы")
    with st.expander("Добавить курс", expanded=not repository.list_courses()):
        with st.form("new_course"):
            title = st.text_input("Название курса")
            description = st.text_area("Описание")
            submitted = st.form_submit_button("Создать курс")
        if submitted:
            if not title.strip():
                st.warning("Укажи название курса.")
            else:
                repository.create_course(title, description)
                st.rerun()

    courses = repository.list_courses()
    if not courses:
        st.info("Создай первый курс.")
        return

    course = st.selectbox("Курс", courses, format_func=lambda item: item.title)
    _render_course_profile_settings(repository, course)
    with st.expander("Добавить модуль"):
        with st.form(f"new_module_{course.id}"):
            module_title = st.text_input("Название модуля")
            module_description = st.text_area("Описание и границы модуля")
            submitted_module = st.form_submit_button("Создать модуль")
        if submitted_module:
            if not module_title.strip():
                st.warning("Укажи название модуля.")
            else:
                repository.add_module(
                    course.id,
                    module_title,
                    description=module_description,
                    scope_text=module_description,
                )
                st.rerun()

    modules = repository.list_modules(course.id)
    if not modules:
        st.info("В курсе пока нет модулей.")
        return

    module = st.selectbox(
        "Модуль",
        modules,
        format_func=lambda item: f"{item.position}. {item.title}",
    )
    st.caption(
        f"Статус: {module.status} · дата изучения: "
        f"{module.learned_date.isoformat() if module.learned_date else 'не задана'}"
    )
    _render_module_profile_settings(repository, module)

    col_material, col_schedule = st.columns([3, 2])
    with col_material:
        st.subheader("Материалы")
        materials = repository.list_materials(module.id)
        for material in materials:
            with st.expander(material.title):
                with st.form(f"edit_material_{material.id}"):
                    edited_title = st.text_input("Название", value=material.title)
                    edited_content = st.text_area(
                        "Текст",
                        value=material.content,
                        height=220,
                    )
                    save_edit = st.form_submit_button("Сохранить исправления")
                if save_edit:
                    try:
                        repository.update_material(
                            material.id,
                            edited_title,
                            edited_content,
                        )
                        st.success("Материал обновлён. Запусти анализ ещё раз.")
                        st.rerun()
                    except ValueError as exc:
                        st.warning(str(exc))

        with st.form(f"material_{module.id}"):
            material_title = st.text_input("Название", value="Конспект")
            material_content = st.text_area("Текст конспекта", height=260)
            add_material = st.form_submit_button("Добавить материал")
        if add_material:
            try:
                repository.add_material(module.id, material_title, material_content)
                st.rerun()
            except ValueError as exc:
                st.warning(str(exc))

        if st.button("Проанализировать материалы с помощью AI", key=f"analyze_{module.id}"):
            service = _service(database_url, provider_name, provider_model)
            with st.spinner("AI выделяет знания и практические навыки..."):
                try:
                    analysis = service.analyze_module(module.id)
                    st.session_state[f"analysis_{module.id}"] = analysis.model_dump()
                    st.success("Карта знаний обновлена.")
                except Exception as exc:
                    st.error("Не удалось проанализировать материалы.")
                    st.code(str(exc))

        analysis_result = st.session_state.get(f"analysis_{module.id}")
        if analysis_result and analysis_result.get("warnings"):
            st.warning("Возможные проблемы в конспекте:")
            for warning in analysis_result["warnings"]:
                st.write(f"- {warning}")

    with col_schedule:
        st.subheader("Карта знаний")
        knowledge = repository.list_knowledge_items(module.id)
        if not knowledge:
            st.info("Добавь конспект и запусти анализ.")
        else:
            theory = [item for item in knowledge if item.kind == "theory"]
            skills = [item for item in knowledge if item.kind == "skill"]
            st.metric("Теоретических знаний", len(theory))
            st.metric("Практических навыков", len(skills))
            with st.expander("Показать карту"):
                for item in knowledge:
                    st.write(f"**{item.title}** · `{item.kind}`")
                    st.caption(item.description)
                    if item.source_excerpt:
                        st.caption(f"Источник: {item.source_excerpt}")

        learned_date = st.date_input(
            "Дата изучения модуля",
            value=module.learned_date or _today_in_app_timezone(),
            key=f"learned_date_{module.id}",
        )
        if st.button("Отметить изученным и создать расписание", key=f"learned_{module.id}"):
            if not knowledge:
                st.warning("Сначала создай карту знаний модуля.")
            else:
                repository.mark_module_studied(module.id, learned_date)
                st.success("Повторения назначены на дни 1, 3, 7, 14 и 30.")
                st.rerun()


def render_today(
    repository: LearningRepository,
    database_url: str,
    provider_name: str,
    provider_model: str,
    today: date,
) -> None:
    st.header("Сегодня")
    assignment_rows = repository.list_due_assignments_with_modules(today)
    if not assignment_rows:
        st.success("На выбранную дату нет повторений.")
        return

    assignment_row = st.selectbox(
        "Повторение",
        assignment_rows,
        format_func=lambda item: _assignment_label(item[0], item[1], today),
    )
    assignment = assignment_row[0]
    review_session = repository.get_session_for_assignment(assignment.id)
    if review_session is None:
        inherited_profile = repository.resolve_training_profile(assignment.module_id)
        assignment_setting = repository.get_training_profile_setting(
            "assignment",
            assignment.id,
        )
        profile_options = ("inherit",) + PROFILE_KEYS
        current_choice = (
            assignment_setting.profile_key if assignment_setting is not None else "inherit"
        )
        st.write(
            f"Будет создано **{assignment.task_count}** заданий. "
            f"Тип: **{'восстановительное' if assignment.kind == 'recovery' else 'регулярное'}**."
        )
        if assignment.reason:
            st.caption(f"Фокус: {assignment.reason}")

        with st.expander("Состав тренировки", expanded=True):
            selected_profile = st.selectbox(
                "Профиль этой тренировки",
                profile_options,
                index=(
                    profile_options.index(current_choice)
                    if current_choice in profile_options
                    else 0
                ),
                format_func=lambda value: (
                    "По настройкам модуля "
                    f"({PROFILE_LABELS[inherited_profile.profile_key]})"
                    if value == "inherit"
                    else _profile_option_label(value)
                ),
                key=f"assignment_profile_{assignment.id}",
            )
            if selected_profile == "inherit":
                plan_profile_key = inherited_profile.profile_key
                plan_config = inherited_profile.config
            else:
                plan_profile_key = selected_profile
                plan_config = (
                    dict(assignment_setting.config or {})
                    if assignment_setting is not None
                    and assignment_setting.profile_key == "custom"
                    else {}
                )
            if selected_profile == "custom":
                plan_config = _custom_profile_editor(
                    f"assignment_custom_{assignment.id}",
                    plan_config,
                )

            plan_errors = (
                custom_config_errors(plan_config)
                if plan_profile_key == "custom"
                else []
            )
            for error in plan_errors:
                st.warning(error)
            knowledge = repository.list_knowledge_items(assignment.module_id)
            task_plan = None
            if not plan_errors:
                try:
                    task_plan = build_task_plan(
                        plan_profile_key,
                        assignment.task_count,
                        (item.kind for item in knowledge),
                        plan_config,
                    )
                    st.markdown(f"**{task_plan.profile_label}**")
                    st.caption(task_plan_summary(task_plan))
                except ValueError as exc:
                    plan_errors = [str(exc)]
                    st.warning(str(exc))

        if st.button(
            "Сгенерировать и начать",
            key=f"generate_{assignment.id}",
            disabled=bool(plan_errors) or task_plan is None,
        ):
            if selected_profile == "inherit":
                repository.clear_training_profile("assignment", assignment.id)
            else:
                repository.set_training_profile(
                    "assignment",
                    assignment.id,
                    selected_profile,
                    plan_config,
                )
            service = _service(database_url, provider_name, provider_model)
            with st.spinner(f"AI готовит {assignment.task_count} заданий..."):
                try:
                    review_session = service.generate_assignment(assignment.id)
                    st.session_state["active_session_id"] = review_session.id
                    st.session_state["active_task_index"] = 0
                    st.rerun()
                except Exception as exc:
                    st.error("Генерация не завершена. Пустая сессия не была создана.")
                    st.code(str(exc))
        return

    render_session(
        repository,
        _service(database_url, provider_name, provider_model),
        review_session.id,
    )


def _assignment_label(
    assignment: ReviewAssignment,
    module_title: str,
    reference_date: date,
) -> str:
    kind = "восстановление" if assignment.kind == "recovery" else f"день {assignment.repetition_day}"
    overdue = (reference_date - assignment.scheduled_date).days
    overdue_text = f" · просрочено {overdue} дн." if overdue > 0 else ""
    return f"{module_title} · {kind} · {assignment.scheduled_date.isoformat()}{overdue_text}"


def render_session(
    repository: LearningRepository,
    service: LearningService,
    session_id: str,
) -> None:
    tasks = repository.list_tasks(session_id)
    if not tasks:
        st.error("Сессия не содержит заданий.")
        return

    index_key = f"task_index_{session_id}"
    initialized_key = f"task_navigation_initialized_{session_id}"
    first_unfinished = next(
        (
            task_index
            for task_index, candidate in enumerate(tasks)
            if candidate.status not in CLOSED_TASK_STATUSES
        ),
        len(tasks) - 1,
    )
    if not st.session_state.get(initialized_key):
        index = first_unfinished
        st.session_state[initialized_key] = True
    else:
        index = min(st.session_state.get(index_key, first_unfinished), len(tasks) - 1)
    st.session_state[index_key] = index
    completed = sum(task.status in CLOSED_TASK_STATUSES for task in tasks)
    st.progress(completed / len(tasks))
    st.caption(f"Завершено: {completed}/{len(tasks)}")
    notice_key = f"task_action_notice_{session_id}"
    notice = st.session_state.pop(notice_key, None)
    if notice:
        st.success(notice)

    task = tasks[index]
    st.subheader(f"Задание {index + 1} из {len(tasks)}")
    st.caption(f"{task.format} · сложность {task.difficulty}/5 · статус {task.status}")
    if task.status == "bad_task":
        st.info("Задание отмечено как плохое, исключено из результатов и завершено.")
    elif task.status == "abandoned":
        st.info("Задание исключено из результатов и завершено без ответа.")
    st.write(task.prompt)
    if task.stimulus:
        st.code(task.stimulus)

    latest_attempt = repository.get_latest_attempt(task.id)
    previous_answer = latest_attempt.user_answer if latest_attempt else None
    answer = render_answer_input(task, previous_answer)
    col_prev, col_submit, col_skip, col_next = st.columns(4)
    with col_prev:
        if st.button("← Назад", disabled=index == 0, key=f"prev_{task.id}"):
            st.session_state[index_key] = index - 1
            st.rerun()
    with col_submit:
        if st.button("Проверить", disabled=task.status in CLOSED_TASK_STATUSES, key=f"submit_{task.id}"):
            if answer in (None, "", []):
                st.warning("Сначала введи ответ.")
            else:
                with st.spinner("Проверяю ответ..."):
                    try:
                        result = service.grade_task(task.id, answer)
                        st.session_state[f"result_{task.id}"] = result.model_dump(mode="json")
                        st.rerun()
                    except Exception as exc:
                        st.error("Не удалось проверить ответ.")
                        st.code(str(exc))
    with col_skip:
        if st.button("Отложить", disabled=task.status in CLOSED_TASK_STATUSES, key=f"skip_{task.id}"):
            repository.set_task_status(task.id, "skipped")
            st.session_state[index_key] = min(index + 1, len(tasks) - 1)
            st.rerun()
    with col_next:
        if st.button("Дальше →", disabled=index == len(tasks) - 1, key=f"next_{task.id}"):
            st.session_state[index_key] = index + 1
            st.rerun()

    result = st.session_state.get(f"result_{task.id}")
    if result is None and latest_attempt is not None:
        result = {
            "verdict": latest_attempt.verdict,
            "feedback": latest_attempt.feedback,
        }
    if result:
        if result["verdict"] == "correct":
            st.success(result["feedback"])
        else:
            st.warning(result["feedback"])

    with st.expander("Проблема с заданием"):
        issue = st.selectbox(
            "Что не так?",
            ["не по теме", "ошибка в условии", "неверный эталон", "непонятная формулировка", "другое"],
            key=f"issue_{task.id}",
        )
        comment = st.text_area("Комментарий", key=f"issue_comment_{task.id}")
        action_disabled = task.status in CLOSED_TASK_STATUSES
        if st.button(
            "Пометить как плохое",
            disabled=action_disabled,
            key=f"bad_{task.id}",
        ):
            repository.add_task_feedback(task.id, issue, comment)
            repository.complete_session_if_ready(session_id)
            refreshed_tasks = repository.list_tasks(session_id)
            st.session_state[index_key] = _next_unfinished_task_index(
                refreshed_tasks,
                index,
            )
            st.session_state[notice_key] = (
                "Жалоба сохранена. Задание исключено из результатов и засчитано "
                "как завершённое."
            )
            st.rerun()
        if st.button(
            "Отказаться от задания",
            disabled=action_disabled,
            key=f"abandon_{task.id}",
        ):
            repository.set_task_status(task.id, "abandoned")
            repository.complete_session_if_ready(session_id)
            refreshed_tasks = repository.list_tasks(session_id)
            st.session_state[index_key] = _next_unfinished_task_index(
                refreshed_tasks,
                index,
            )
            st.session_state[notice_key] = (
                "Задание исключено из результатов и засчитано как завершённое."
            )
            st.rerun()


def _next_unfinished_task_index(tasks: list[Task], current_index: int) -> int:
    if not tasks:
        return 0
    ordered_indexes = list(range(current_index + 1, len(tasks))) + list(
        range(0, current_index)
    )
    return next(
        (
            task_index
            for task_index in ordered_indexes
            if tasks[task_index].status not in CLOSED_TASK_STATUSES
        ),
        min(current_index, len(tasks) - 1),
    )


def _text_answer(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False, indent=2)
    return str(value)


def _option_index(options: list[str], value: Any) -> int | None:
    if value is None:
        return None
    normalized = str(value).strip().casefold()
    return next(
        (
            index
            for index, option in enumerate(options)
            if option.strip().casefold() == normalized
        ),
        None,
    )


def render_answer_input(task: Task, previous_answer: Any = None) -> Any:
    key = f"answer_{task.id}"
    if task.format == "single_choice":
        return st.radio(
            "Ответ",
            task.options,
            key=key,
            index=_option_index(task.options, previous_answer),
        )
    if task.format == "multiple_choice":
        selected = previous_answer if isinstance(previous_answer, list) else []
        return st.multiselect(
            "Ответ",
            task.options,
            default=[item for item in selected if item in task.options],
            key=key,
        )
    if task.format == "true_false":
        true_false_options = ["Верно", "Неверно"]
        if isinstance(previous_answer, bool):
            previous_answer = "Верно" if previous_answer else "Неверно"
        return st.radio(
            "Ответ",
            true_false_options,
            key=key,
            index=_option_index(true_false_options, previous_answer),
        )
    if task.format == "ordering":
        default = (
            "\n".join(str(item) for item in previous_answer)
            if isinstance(previous_answer, list)
            else _text_answer(previous_answer)
        )
        value = st.text_area("Порядок — один пункт на строку", value=default, key=key)
        return [line.strip() for line in value.splitlines() if line.strip()]
    if task.format == "matching":
        value = st.text_area(
            "Соответствия в JSON, например {\"термин\": \"определение\"}",
            value=_text_answer(previous_answer),
            key=key,
        )
        try:
            return json.loads(value) if value.strip() else {}
        except json.JSONDecodeError:
            return value
    return st.text_area(
        "Ответ",
        value=_text_answer(previous_answer),
        height=220,
        key=key,
    )


def render_progress(repository: LearningRepository) -> None:
    st.header("Прогресс")
    rows = repository.get_progress_overview()
    if not rows:
        st.info("Пока нет курсов.")
        return

    course_ids = list(dict.fromkeys(row.course_id for row in rows))
    for course_id in course_ids:
        course_rows = [row for row in rows if row.course_id == course_id]
        st.subheader(course_rows[0].course_title)
        module_rows = [row for row in course_rows if row.module_id is not None]
        if not module_rows:
            st.caption("Нет модулей.")
            continue
        for row in module_rows:
            st.write(
                f"**{row.module_position}. {row.module_title}** · "
                f"статус `{row.module_status}` · попыток: {row.attempt_count}"
            )


def render_migration(repository: LearningRepository) -> None:
    st.header("Миграция Python Trainer")
    st.write(
        "Импорт переносит темы, материалы, расписание, сессии, задания, ответы и "
        "фидбек из текущей Google Таблицы. Операция повторяемая: существующие "
        "legacy-ID не дублируются."
    )

    try:
        google_configured = bool(st.secrets.get("GOOGLE_SHEET_ID")) and bool(
            st.secrets.get("gcp_service_account")
        )
    except Exception:
        google_configured = False
    if not google_configured:
        st.info("Для миграции сохрани прежние GOOGLE_SHEET_ID и gcp_service_account в secrets.")
        return

    if st.button("Проверить данные без записи"):
        from learning_app.legacy_google import load_legacy_snapshot
        from learning_app.legacy_migration import LegacyMigrator

        with st.spinner("Читаю старую Google Таблицу..."):
            try:
                snapshot = load_legacy_snapshot(st.secrets)
                report = LegacyMigrator(repository).inspect(snapshot)
                st.session_state["legacy_migration_report"] = report
                st.session_state["legacy_snapshot"] = snapshot
            except Exception as exc:
                st.error("Не удалось проверить старые данные.")
                st.code(str(exc))

    report = st.session_state.get("legacy_migration_report")
    if not report:
        return

    st.json(
        {
            "темы": report.topics,
            "сессии": report.sessions,
            "задания": report.tasks,
            "ответы": report.answers,
            "материалы": report.materials,
            "восстановленные архивные темы": report.restored_topics,
            "нарушенные ссылки": report.unresolved_references,
        }
    )
    if report.restored_topics:
        st.info(
            "Миграция автоматически восстановит отсутствующие темы как архивные: "
            + ", ".join(report.restored_topics)
            + ". Исторические сессии и ответы сохранятся."
        )
    if report.unresolved_references:
        st.error("Сначала исправь нарушенные ссылки в исходной таблице.")
        return

    confirmed = st.checkbox("Я проверил количество записей и хочу выполнить импорт")
    if st.button("Импортировать в новую базу", disabled=not confirmed):
        from learning_app.legacy_migration import LegacyMigrator

        with st.spinner("Переношу историю Python Trainer..."):
            try:
                result = LegacyMigrator(repository).migrate(
                    st.session_state["legacy_snapshot"]
                )
                st.success(
                    f"Импорт завершён: {result.topics} тем, {result.sessions} сессий, "
                    f"{result.tasks} заданий и {result.answers} ответов."
                )
            except Exception as exc:
                st.error("Миграция отменена. Транзакция не была частично сохранена.")
                st.code(str(exc))
