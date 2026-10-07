# Learning App — living product specification

## Product goal

A private, single-user web application for learning and spaced repetition across
different courses. The existing Python course remains active and must continue
without losing progress.

## Core journeys

1. Create a course and add modules manually.
2. Add one or more theory notes to a module.
3. Let AI extract grounded theory points and in-scope practical skills.
4. Mark the module as studied on an explicit date.
5. Complete regular reviews on days 1, 3, 7, 14, and 30.
6. Receive a short recovery review the day after weak performance.
7. Inspect progress, prior attempts, feedback, and upcoming reviews.

## Functional requirements

- A course contains ordered modules.
- A module can contain multiple editable source materials.
- Theory questions must be grounded in the supplied materials.
- Practical tasks may use general AI knowledge, but must stay inside the module
  scope and must not introduce future material as a requirement.
- Theory formats are extensible and initially include single choice, multiple
  choice, true/false, matching, ordering, fill-in-the-blank, and open answer.
- Practical formats initially include debugging, output prediction, code or
  configuration authoring, and open practical answers.
- A regular review contains 40 items and progresses from easier to harder work.
- A recovery review contains 15–20 new variants focused on weak knowledge and
  skills. It is due the day after the triggering mistakes and does not move the
  regular schedule.
- New generations consider previous tasks, attempts, verdicts, error types, and
  feedback. They increase coverage of weak areas without dropping broad module
  coverage.
- A learner can flag a bad task. Bad tasks do not count as learner mistakes.
- Suspected contradictions or obvious source problems are shown as warnings;
  source text is never silently rewritten.

## Business rules

- Regular review days: 1, 3, 7, 14, 30 after `learned_date`.
- Correct attempts increase mastery; partial and incorrect attempts reduce it.
- Weak knowledge receives more weight in future generation.
- Incorrect or partially correct performance may create one recovery review for
  the next day. Duplicate open recovery reviews for the same module/day are not
  created.
- Skipping an item does not permanently complete it. A skipped item remains
  available for retry or is explicitly abandoned by the learner.
- Completing a session requires every valid item to be correct or explicitly
  abandoned. Flagged bad tasks are excluded.
- AI output is validated before a session is committed. A failed generation
  must not leave an empty session.

## Migration contract

The migration preserves the current Python course, topics/modules, generated
tasks, sessions, answers and feedback, topic materials, learned dates, and
scheduled review dates. The legacy `mistakes` table is optional because mastery
can be rebuilt from attempts. Legacy identifiers are retained for traceability.

## UX defaults

- Streamlit remains the web UI for the first version.
- No mandatory moderation screen blocks the first session.
- Extracted knowledge and skills can be reviewed or edited later.
- A module enters the spaced-repetition schedule only after an explicit
  "mark as studied" action/date.
- One lightweight private login is sufficient; roles and collaboration are out
  of scope.

## Out of scope for the first version

- Multi-user accounts, sharing, teacher dashboards, billing, certificates.
- Automatic ingestion of an entire Udemy course.
- Automatic web research for theory answers.
- Executing arbitrary learner code on the application server.

## Traceability

- **Explicit:** single user; multiple courses; manual modules; supplied theory;
  AI-generated theory and practical training; 40-item regular reviews;
  15–20-item next-day recovery reviews; adaptive use of attempt history;
  preservation of the active Python course and history.
- **Inferred:** tasks must be migrated so preserved answers remain meaningful;
  theory source text is authoritative; existing Streamlit delivery should be
  evolved rather than replaced.
- **Implementation decisions:** provider-neutral AI boundary; relational
  persistence; explicit source excerpts; no mandatory content-approval gate.
