# Technical design

## Shape

The first version stays a single Streamlit application with three boundaries:

- `learning_app.repository`: transactional persistence and migrations;
- `learning_app.services`: scheduling, mastery, generation, and grading;
- `learning_app.ai`: replaceable Grok and Gemini providers using validated
  structured output.

The UI calls services rather than Google Sheets or a model SDK directly.

## Persistence

Use SQLAlchemy with SQLite for local development and PostgreSQL through
`DATABASE_URL` in hosted environments. Schema creation is deterministic and
idempotent. Database transactions ensure a generated task set and its session
are committed together.

Core entities:

- `courses`
- `modules`
- `materials`
- `knowledge_items` (`theory` or `skill`, with source excerpt)
- `sessions` (`regular` or `recovery`)
- `tasks`
- `task_knowledge_items`
- `attempts`
- `task_feedback`
- `training_profile_settings` (course, module, or one-session overrides)

Legacy IDs are stored on migrated records. JSON columns hold answer options,
matching pairs, and provider metadata while stable query fields remain normal
columns.

## AI boundary

`AIProvider` exposes structured operations:

- analyze module material;
- generate a session plan and tasks;
- grade an open or practical response.

Deterministic theory formats are graded locally. Open and practical responses
are graded by AI. The Grok adapter uses `grok-4.7` structured outputs through
xAI's documented OpenAI-compatible endpoint. Gemini is retained as an optional
adapter during migration. Provider selection comes from `AI_PROVIDER`; secrets
never enter prompts or the database.

Generation receives a compact learning profile, not an unbounded transcript:
knowledge mastery, recent representative tasks, recent attempts, normalized
error types, and task complaints. The prompt clearly separates trusted product
instructions from untrusted user/source content.

The application resolves the profile in assignment → module → course order and
turns it into an exact integer task plan. Generic profiles constrain the three
groups (creation, analysis, theory); the coding profile constrains exact formats.
The validator keeps conforming unique tasks and asks the provider only for the
missing group or format counts.

## Reliability

- Validate item count, formats, options, answers, difficulty, and knowledge IDs.
- Generate before opening the transaction; commit session and tasks together.
- Use an idempotency key for each scheduled review.
- Retry transient provider errors, but do not retry validation indefinitely.
- Preserve a failed-generation record without creating an unusable session.
- Pin runtime and direct dependencies.

## Migration

The legacy Google Sheets migration is repeatable and keyed by legacy IDs. It
creates a `Python` course, converts topics to modules, then imports materials,
sessions, tasks, and answers. Old mistake rows are not required. A dry-run
report shows counts and unresolved references before commit.

## Verification strategy

- Unit tests: scheduling, mastery weights, local grading, task validation.
- Repository tests against temporary SQLite: transactions and idempotency.
- Migration tests with in-memory legacy fixtures.
- Provider contract tests with fakes; live API tests remain opt-in.
- Streamlit smoke test plus manual verification of the critical user journey.
