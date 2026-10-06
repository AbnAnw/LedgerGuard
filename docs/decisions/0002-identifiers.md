# ADR-0002: Opaque domain identifiers and scoped source identifiers

- **Status:** Accepted
- **Date:** 2026-10-06
- **Decision owners:** LedgerGuard engineering

## Context

Identifiers must be safe to expose in APIs, usable before database insertion, independent across local and background processes, and resistant to enumeration. External source identifiers are useful for idempotency but are neither globally unique nor controlled by LedgerGuard.

## Decision

- Use application-generated UUIDv4 values for domain primary keys and correlation/request/job identifiers.
- Store UUIDs in native PostgreSQL `UUID` columns and serialize them in lowercase canonical form.
- Validate client-supplied identifiers but do not permit clients to select primary keys for created domain records.
- Retain external `source_record_id` values as ordinary strings with uniqueness scoped to the owning account/source boundary.
- Scope batch `idempotency_key` to `source_system` and bind it to a SHA-256 payload digest; same key/same digest is a retry, while same key/different digest is a conflict.
- Use `BIGINT GENERATED ALWAYS AS IDENTITY` only where strict database ordering or a human-friendly display number is needed: audit sequence and case number. These values are not authorization secrets and are not the public API identity.
- Do not encode entity type, time, tenant, or business meaning in primary keys.

## Consequences

- API identifiers do not expose record counts or creation order.
- Services and workers can allocate IDs before a transaction is committed.
- UUIDv4 random insertion may have lower index locality than ordered identifiers; Day 17 will measure before considering change.
- Stable chronological ordering uses an explicit timestamp plus UUID tie-breaker, or the audit identity sequence where total order is required.
- Database constraints and payload fingerprints, rather than primary key reuse, enforce idempotency.

## Alternatives rejected

- **Auto-increment IDs everywhere:** compact but enumerable, database-coupled, and unsuitable for pre-allocation.
- **UUIDv7:** attractive ordering properties, but current standard-library/database generation support is less uniform across the intended local stack; revisit only with measured need.
- **External IDs as primary keys:** exposes source coupling and cannot guarantee global uniqueness or immutability.
- **ULID:** readable and ordered, but adds encoding/library choices without a measured benefit for version 1.
