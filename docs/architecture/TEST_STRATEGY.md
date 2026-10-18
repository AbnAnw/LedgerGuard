# Automated Test Strategy

## Purpose

Day 14 turns LedgerGuard's existing feature tests into a repeatable release gate. The suite must
prove the highest-risk financial, authorization, retry, and investigation behaviours at the
lowest practical layer, then exercise the three user roles through a real browser and service
topology. All fixtures and credentials are synthetic.

## Test layers and contracts

| Layer | Scope | Required evidence | Failure meaning |
| --- | --- | --- | --- |
| Unit/service | Pure validation and service logic with isolated SQLAlchemy sessions | Matching determinism, fraud boundaries, case transitions, decimal money, permission matrix, and idempotent replay | A domain contract changed or regressed |
| Component/API | FastAPI and React components with controlled dependencies | Authentication, HTTP authorization, error states, safe rendering, and frontend money formatting | An application boundary no longer enforces the contract |
| Integration | PostgreSQL, Redis, and a live Celery worker from Docker Compose | Database constraints, append-only audit history, broker reachability, worker execution, retry persistence, and duplicate-delivery safety | The real service topology behaves differently from isolated tests |
| Browser journey | Chromium against the live frontend and API | Administrator, operations analyst, and auditor see only their permitted workspaces and can complete their critical journey | The assembled product or role-specific interface is unusable |

Unit and component tests run without external services. Integration and browser tests are opt-in
locally because they require Docker Compose. CI starts an isolated Compose project, migrates and
seeds it, then runs both layers against that topology.

## Risk-based coverage matrix

| Risk | Required automated cases |
| --- | --- |
| Binary floating-point or rounding affects money | External monetary values reject floats; accepted values remain exact `Decimal`; database columns remain fixed precision; frontend formatting never converts the amount to `number` |
| Reconciliation changes with input order or a time boundary | Equivalent permutations produce identical classifications/evidence digests; inclusive and out-of-window boundaries are explicit |
| Fraud rules alert without sufficient evidence | Each rule has triggering and non-triggering examples; threshold and half-open time-window boundaries are covered; evidence is deterministic |
| A role gains unintended authority | A deny-by-default API permission matrix covers all three roles and unauthenticated callers; browser journeys assert role-specific navigation and controls |
| Invalid case state changes bypass the workflow | Every allowed transition and representative invalid, same-state, unresolved, and reopen paths are tested |
| Retry or duplicate delivery creates a second financial fact | Exact replay, changed-payload conflict, database race, terminal redelivery, real worker execution, and bounded retry state are covered |
| CI passes while an assembled service is broken | CI runs formatting, lint, strict typing, unit/component tests, builds, migrations, integration tests, and all three Chromium journeys |

## Browser personas and journeys

- **Administrator:** signs in, sees Administration, Operations, and read-only Audit evidence
  workspaces, can reach all evidence-oriented navigation, and signs out.
- **Operations analyst:** signs in, sees Operations but not Administration or Audit evidence,
  can inspect reconciliation evidence, fraud alerts, cases, and verified reports, and is shown
  write controls.
- **Auditor:** signs in, sees Audit evidence but not Operations or Administration, can inspect
  reconciliation, alerts, cases, reports, and audit history, and is not shown write controls.

Selectors use accessible roles and names rather than CSS implementation details. Journeys must not
depend on ordering between tests, production data, or wall-clock-sensitive facts. The local and CI
harnesses use only documented synthetic seed commands to establish any required evidence.

## CI isolation and artifacts

- Backend and frontend quality jobs use locked dependencies and run independently.
- The end-to-end job uses a unique Compose project name, waits for health checks, runs the current
  Alembic head, and idempotently loads the synthetic base, reconciliation, and fraud fixtures.
- Playwright retains traces and screenshots only for failed retries; CI uploads those diagnostics
  without committing them to Git.
- Compose logs are uploaded on failure and the isolated stack is always removed after the job.
- No workflow contains credentials other than the documented local-only `.invalid` demonstration
  identities and password. Production credentials and real data are forbidden.

## Day 14 acceptance criteria

Day 14 is complete only when:

1. the risk matrix above is represented by automated tests, including newly added adversarial
   money, permission, retry, database, and worker cases;
2. administrator, operations analyst, and auditor Playwright journeys pass against the live stack;
3. GitHub Actions runs backend format/lint/type/test checks, frontend lint/type/test/build checks,
   PostgreSQL/Redis/Celery integration checks, and Playwright Chromium journeys;
4. a clean local run of the same relevant commands passes and exact measured results are recorded
   in `PROGRESS.md`;
5. generated reports, traces, browser binaries, caches, secrets, and build output remain untracked.
