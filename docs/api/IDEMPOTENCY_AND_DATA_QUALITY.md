# Ingestion Idempotency and Data Quality

## Purpose

This document defines the Day 6 retry, duplicate, conflict, and batch-quality contract for transaction ingestion schema `1.0`. The existing JSON and CSV endpoints share these rules.

## Request contract

Every ingestion request must include an `Idempotency-Key` header. A key:

- is scoped to `source_system`;
- contains 1–200 letters, digits, `.`, `_`, `:`, or `-` characters;
- identifies one canonical batch payload, including schema version, source account, and records;
- is not a credential and may be retained as operational evidence.

LedgerGuard hashes the canonical batch payload with SHA-256. JSON object key order does not affect the hash. The original filename is not part of the fingerprint, so resubmitting the same CSV content under another local filename remains the same request.

## Retry outcomes

| Situation | HTTP result | Persistence result |
| --- | --- | --- |
| New key and payload | `202 Accepted` | One durable job is committed and published; financial processing continues in Celery |
| Existing key and identical payload hash | `200 OK` | Existing job is returned and a queued job is safely republished; no duplicate job is created |
| Existing key and different payload hash | `409 Conflict` with `IDEMPOTENCY_KEY_REUSED` | No rows are created or changed |

The durable job owns a unique hash of `(kind, source_system, idempotency_key)` and the ingestion batch retains PostgreSQL uniqueness on `(source_system, idempotency_key)`. The service also locks the selected source account while classifying records so concurrent deliveries for one account cannot create two facts for one source identifier.

## Source-record outcomes

Only records that pass the schema `1.0` field validation participate in duplicate/conflict comparison.

| Situation | Outcome | Reason code | New transaction |
| --- | --- | --- | :---: |
| Source identifier has not been seen for the account | `accepted` | None | Yes |
| Identifier exists and all normalized business fields agree | `duplicate` | `DUPLICATE_SOURCE_RECORD` | No |
| Identifier exists but any normalized business field differs | `conflict` | `CONFLICTING_SOURCE_RECORD` | No |
| Record fails schema validation | `rejected` | Existing field-specific code(s) | No |

Comparison covers source reference, decimal amount, currency, direction, status, UTC occurrence time, and optional instrument fingerprint. Decimal scale and timezone presentation differences do not create false conflicts when their normalized values are equal.

The same rules apply to repeated identifiers within one batch and identifiers already stored by an earlier batch. PostgreSQL uniqueness on `(account_id, source_record_id)` remains the final financial-record safeguard.

## Batch quality summary

Every completed or replayed batch persists:

- accepted, rejected, duplicate, and conflict counts;
- issue count (`rejected + duplicate + conflict`);
- acceptance rate as a decimal string percentage with two fractional digits;
- deterministic reason-code counts;
- `clean` when every source row was accepted, otherwise `issues_detected`.

Terminal batch counts must add up to `source_count`. PostgreSQL enforces this invariant in addition to application checks.

## Atomicity and evidence

The batch, accepted financial facts, and every row outcome commit in one database transaction. A database error rolls the unit back. Duplicate and conflict evidence never links to a newly created transaction and never echoes the competing stored financial values in an API error.

## Verification scenarios

Day 6 is complete only when automated and live checks prove:

1. an exact request retry returns the original job and duplicate worker delivery creates no additional batch, record, or transaction;
2. reusing a key for changed content returns `409` and creates nothing;
3. same-batch and prior-batch duplicates create no new financial fact;
4. same-batch and prior-batch conflicts create no new financial fact;
5. invalid records, duplicates, conflicts, and accepted rows produce deterministic summary counts;
6. database constraints reject an impossible terminal total and duplicate financial source identifier.
