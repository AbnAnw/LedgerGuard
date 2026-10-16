# Audit logging contract

## Purpose and boundary

LedgerGuard audit events are append-only decision evidence, not diagnostic logs. They let an
auditor reconstruct who attempted an action, what authoritative object was involved, whether the
action succeeded, and which stored evidence changed. Application logs may be rotated; audit events
follow the retention assumptions in the data model.

The application writes successful domain changes and their audit event in the same PostgreSQL
transaction. Denied authentication, authorization, and rejected integrity transitions create a
minimal event in a separate transaction because there is no domain change to commit.

## Event vocabulary

Actions use stable lower-case dotted names. Day 12 covers:

- `auth.login`, `auth.logout`, and `authz.permission_denied`;
- `job.queued`, `job.replayed`, `job.cancelled`, and worker terminal outcomes;
- `transaction.ingestion.completed` and `reconciliation.run.completed`;
- `fraud.rule.created`, `fraud.rule.version_created`, `fraud.evaluation.completed`, and
  `fraud.alerts.read`;
- `case.created`, `case.assigned`, `case.comment_added`, `case.alerts_linked`,
  `case.transitioned`, and `case.read`;
- `audit.history.read` and `audit.case_timeline.read`.

Every event contains a database sequence, UUID, UTC occurrence time, actor type and optional user,
action, target type and optional UUID, result, correlation UUID, optional request/job UUIDs,
allowlisted before/after states, and allowlisted metadata.

## Redaction and size policy

Audit JSON is explicit and bounded. Passwords, password hashes, bearer tokens, credentials,
secrets, raw uploads, CSV bodies, and unrestricted request payloads are forbidden at the shared
write boundary.
Each state snapshot is limited to 16 KiB and metadata to 8 KiB after canonical JSON encoding.
Authentication attempts store only a SHA-256 digest of the normalized email plus a reason code;
they never store the email or password. Error metadata uses stable codes, not stack traces or raw
database messages.

## Read API and permissions

- `GET /api/v1/audit/events` supports actor, action, target, result, correlation, UTC range, and
  sequence-cursor filters.
- `GET /api/v1/audit/cases/{case_id}/timeline` returns the linked transaction, alert, and case audit
  chain in database-sequence order.
- Only principals with `audit:read` may use these endpoints. Administrators and auditors have that
  permission; operations analysts do not.
- Reading audit history is itself audited. There are no update or delete endpoints.

The case timeline exposes relationship identifiers but not unrestricted transaction payloads. The
auditor can follow transaction ingestion evidence to a fraud alert, its case creation, and each
investigation transition.

## Database safeguards

PostgreSQL already rejects every update or delete on `audit_events`. Day 12 additionally enforces
the actor/user pairing, action and target naming, JSON-object shape, and presence of non-empty
metadata. The runtime uses insert and select operations only.

## Edge cases and tests

- Unknown login, incorrect password, disabled/locked user, successful login, and logout produce
  sanitized events.
- Permission denials record the HTTP method, route, and required permission names without request
  content.
- An invalid case transition records a denied event without mutating the case.
- Exact job or fraud replays are distinguishable from newly created work.
- Oversized, non-object, or secret-bearing JSON is rejected before persistence.
- Auditor reads pass, analyst reads fail, and update/delete remain impossible at both API and
  database boundaries.

## Day 12 acceptance criteria

1. Authentication, security-sensitive reads, and writes affecting transactions, rules,
   reconciliation, alerts, and cases emit structured audit evidence.
2. Each event identifies actor, UTC time, target, action, result, and correlation, with bounded
   allowlisted state where relevant.
3. Audit events cannot be changed or deleted through the API or PostgreSQL trigger.
4. An auditor can reconstruct a synthetic transaction-to-alert-to-case lifecycle in sequence order.
