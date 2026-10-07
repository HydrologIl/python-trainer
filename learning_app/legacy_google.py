from __future__ import annotations

from typing import Any, Mapping

from learning_app.legacy_migration import LegacySnapshot


def load_legacy_snapshot(secrets: Mapping[str, Any]) -> LegacySnapshot:
    try:
        import gspread
        from google.oauth2.service_account import Credentials
    except ImportError as exc:
        raise RuntimeError("Для импорта установи gspread и google-auth.") from exc

    sheet_id = str(secrets.get("GOOGLE_SHEET_ID") or "")
    if not sheet_id:
        raise ValueError("Не задан GOOGLE_SHEET_ID.")
    account = dict(secrets["gcp_service_account"])
    credentials = Credentials.from_service_account_info(
        account,
        scopes=["https://www.googleapis.com/auth/spreadsheets.readonly"],
    )
    spreadsheet = gspread.authorize(credentials).open_by_key(sheet_id)

    def records(name: str, optional: bool = False) -> list[dict[str, Any]]:
        try:
            return spreadsheet.worksheet(name).get_all_records()
        except gspread.WorksheetNotFound:
            if optional:
                return []
            raise

    return LegacySnapshot(
        topics=records("topics"),
        sessions=records("sessions"),
        tasks=records("tasks"),
        answers=records("answers"),
        materials=records("topic_materials", optional=True),
    )
