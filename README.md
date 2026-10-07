# Learning App

Personal Streamlit application for multi-course learning, spaced repetition,
adaptive theory tests, and practical skill training.

The repository contains two modes:

- `legacy` — the current Python Trainer backed by Google Sheets;
- `universal` — the new course-agnostic application backed by a relational
  database.

`legacy` remains the default so deploying this branch cannot interrupt the
active Python course before migration is complete.

## Local setup

Use Python 3.11.

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .streamlit/secrets.toml.example .streamlit/secrets.toml
streamlit run python_trainer.py
```

For local universal-mode development, `sqlite:///learning_app.db` is sufficient.
For Streamlit Cloud, configure a persistent PostgreSQL database through
`DATABASE_URL`.

## Configuration

Important Streamlit secrets:

- `APP_MODE`: `legacy` or `universal`;
- `APP_PASSWORD`: private single-user access;
- `APP_TIMEZONE`: calendar timezone, for example `Asia/Yerevan`;
- `DATABASE_URL`: SQLAlchemy PostgreSQL URL for hosted universal mode;
- `AI_PROVIDER`: `xai` or `gemini`;
- `XAI_API_KEY` and optional `XAI_MODEL` (default `grok-4.7`);
- `GEMINI_API_KEY` and optional `GEMINI_MODEL`;
- existing `GOOGLE_SHEET_ID` and `gcp_service_account` for legacy mode and
  migration.

## Safe migration sequence

1. Deploy the code while keeping `APP_MODE = "legacy"`.
2. Provision PostgreSQL and set `DATABASE_URL` and `APP_PASSWORD`.
3. Switch temporarily to `APP_MODE = "universal"`.
4. Open **Миграция**, run the dry check, and verify record counts.
5. Run the import. It is transactional and repeatable by legacy ID.
6. Verify the Python course, modules, sessions, tasks, answers, materials, and
   dates before continuing in universal mode.

The old Google Sheet is read-only during migration and remains a rollback copy.

## Tests

```bash
python -m unittest discover -s tests -v
```

The live Grok and Gemini calls are deliberately not part of the default test
suite. Core scheduling, mastery, grading, repository transactions, and legacy
migration are tested without external services.

Product requirements and technical decisions live in
[`docs/PRODUCT.md`](docs/PRODUCT.md) and
[`docs/TECHNICAL_DESIGN.md`](docs/TECHNICAL_DESIGN.md).
