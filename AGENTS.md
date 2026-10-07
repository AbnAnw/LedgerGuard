# LedgerGuard Repository Instructions

These instructions apply to the entire repository.

## Delivery discipline

- Treat the repository as the source of truth for implementation, tests, architecture decisions, and exact status.
- Use the existing project-memory files rather than creating duplicate documents:
  - `PROJECT_PLAN.md` is the roadmap and acceptance-criteria record (equivalent to `docs/ROADMAP.md`).
  - `PROGRESS.md` is the concise current-state record (equivalent to `docs/PROJECT_STATE.md`).
  - `docs/decisions/` contains the architectural decision records (equivalent to `docs/DECISIONS.md`).
- At the start of every `Next`, read this file and `PROGRESS.md`; inspect the current branch, working tree, and recent commits; then read only the roadmap section and technical documents relevant to the next unfinished day.
- Reconcile documentation against code and Git history when they disagree. Do not repeat completed work because an external checkbox is stale.
- Complete exactly one roadmap day for each user command of `Next`.
- Preserve user-authored and unexpected working-tree changes. Never reset, revert, or overwrite them.
- Establish the day's acceptance criteria, inspect existing implementation, implement only that day's scope, add relevant tests, run appropriate checks, review the final diff, update project memory, and commit verified work.
- Do not push, create remotes, publish releases, or deploy without explicit authorization.
- Do not rewrite Git history or force-push.

## Commit standard

- Create at least one focused, verified commit for every completed roadmap day.
- Stage only files belonging to the current work and inspect the staged diff before committing.
- Use Conventional Commits: `type(scope): imperative summary`.
- Prefer `feat`, `fix`, `test`, `docs`, `refactor`, `chore`, `ci`, `perf`, or `security`.
- Describe the outcome with an imperative verb. Add a body when reasoning or trade-offs are not obvious, and mention the roadmap day when useful.
- Do not use vague summaries such as `updates`, `changes`, `work`, `fix stuff`, or `day done`.

## Notion synchronization

- Use Notion as the concise user-facing workspace for roadmap/milestones, current progress, completed-day summaries, important decisions, risks/blockers, portfolio presentation, and relevant links or commit references.
- Do not duplicate large technical documents from the repository into Notion.
- After a roadmap day is successfully committed, update and verify the corresponding LedgerGuard Notion entry with status, short outcome, decisions, test results, blockers/deferred work, commit hash/message, and next day.
- Preserve useful existing Notion content and improve its structure only when doing so clearly helps navigation, planning, memory, or portfolio presentation.
- If Notion is unavailable, complete the repository work, put the concise synchronization content in `PROGRESS.md`, report synchronization as pending, and never claim success without verification.

## Engineering constraints

- Use only synthetic demonstration data.
- Never use binary floating point for money. Use decimal types in application code and fixed-precision numeric columns in PostgreSQL.
- Store timestamps in UTC. Convert time zones only at display boundaries and label the displayed zone.
- Validate external input and reinforce important invariants with database constraints.
- Make ingestion and background jobs idempotent and safe to retry.
- Keep audit evidence for reconciliation decisions, alerts, and investigations.
- Enforce authorization in the backend even when the interface hides an action.
- Keep cloud integration behind adapters so local development does not depend on GCP.
- Do not commit secrets, `.env` files, real financial data, generated credentials, or build artifacts.
- Do not claim test, security, performance, or coverage results unless they were measured.

## Quality expectations

- Add migrations for every database schema change.
- Test success, failure, permission, duplicate, and retry paths when relevant.
- Run the checks appropriate to the completed day and record exact results in `PROGRESS.md`.
- Update documentation and the plan status as part of the same daily commit.
- A day is complete only when acceptance criteria pass, the final diff is reviewed, project memory matches reality, commits succeed, Notion is verified or explicitly pending, and no accidental working-tree changes remain.
