# LedgerGuard Repository Instructions

These instructions apply to the entire repository.

## Delivery discipline

- Read `PROJECT_PLAN.md`, `PROGRESS.md`, and recent Git history before starting a roadmap day.
- Complete exactly one roadmap day for each user command of `Next`.
- Preserve user-authored and unexpected working-tree changes. Never reset, revert, or overwrite them.
- Use one local commit per completed day with the format `day-XX: concise description`.
- Do not push, create remotes, publish releases, or deploy without explicit authorization.

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
