# Case-management contract

## Purpose

LedgerGuard cases give operations analysts a controlled investigation record for one or more
fraud alerts. The API is the authorization boundary; interface visibility is only a convenience.
All timestamps are stored and returned with UTC offsets. The interface labels displayed times as
UTC.

## Roles

- Administrators and operations analysts may create, assign, comment on, link alerts to, and
  transition cases.
- Auditors may read the queue and complete case evidence, but cannot mutate it.
- A case may be assigned only to an active administrator or operations analyst. It may also be
  explicitly unassigned.

## Aggregate and optimistic concurrency contract

A case contains its metadata, linked alerts, append-only comments, and append-only status
history. Every mutation requires the caller's `expected_version`; a stale version returns HTTP
409 with `CASE_VERSION_CONFLICT`. Successful mutations increment the case version exactly once.
This prevents silent overwrites when two analysts act on the same case.

Normal workflow permits an alert to belong to only one case. Attempts to relink an alert already
held by another case are rejected. A future exceptional merge workflow may relax this rule only
with an explicit audit record.

## Lifecycle

| From | Allowed next status |
| --- | --- |
| Created | `open` |
| `open` | `in_review`, `escalated` |
| `in_review` | `escalated`, `resolved` |
| `escalated` | `in_review`, `resolved` |
| `resolved` | `reopened` |
| `reopened` | `in_review`, `escalated`, `resolved` |

Every transition requires a non-blank reason and records actor, old state, new state, correlation
ID, and UTC time. Resolution additionally requires a code (`confirmed_issue`, `false_positive`,
`no_action`, or `duplicate`) and a summary. Resolving with `confirmed_issue` closes linked alerts;
the other resolution codes dismiss them. Reopening returns linked alerts to `in_review` and clears
their closure metadata. Resolution fields are absent on every non-resolved case.

## API contracts

- `POST /api/v1/cases` creates an open case and links one or more alerts.
- `GET /api/v1/cases` filters by owner/unassigned, priority, status, rule code, and minimum age.
- `GET /api/v1/cases/{case_id}` returns linked alert evidence, comments, and status history.
- `PATCH /api/v1/cases/{case_id}/assignment` assigns or unassigns a case.
- `POST /api/v1/cases/{case_id}/comments` appends a comment.
- `POST /api/v1/cases/{case_id}/alerts` links more unclaimed alerts.
- `POST /api/v1/cases/{case_id}/transitions` applies one valid lifecycle transition.

External strings are stripped and length-limited. Identifiers are UUIDs. Unknown cases, users,
alerts, and rules return 404 without exposing database details. Database constraints independently
protect case text, resolution state, version, and history invariants.

## Queue behaviour

The investigation queue prioritises critical, high, medium, then low cases; within a priority it
shows the oldest update first. `min_age_hours` is computed from case creation time. Rule filtering
matches the immutable rule code behind a linked alert. Repeated joins are deduplicated.

## Edge cases and tests

- Duplicate alert IDs in a request and alerts linked to another case are rejected.
- Disabled users, auditors, and users without an active role cannot become owners.
- Empty comments, reasons, titles, and resolution summaries are rejected.
- Same-state, skipped, and backward transitions are rejected.
- Resolution data on a non-resolution transition is rejected.
- Stale versions are rejected without partial writes.
- Auditor reads succeed while every auditor mutation is forbidden.
- A deterministic integration journey covers create, assign, comment, review, escalate, resolve,
  and reopen, and verifies persisted history plus linked-alert status changes.

## Day 11 acceptance criteria

1. An analyst can create a case from an alert, assign it, comment, escalate, resolve, and reopen it.
2. Every state change retains sufficient actor, reason, time, and correlation evidence.
3. Queue filters cover owner, unassigned state, priority, status, rule, and age.
4. Invalid transitions, stale writes, invalid owners, duplicate alert claims, and auditor writes are
   rejected by automated tests.
5. The interface exposes analyst controls and a read-only auditor view with loading, empty, and
   error states.
