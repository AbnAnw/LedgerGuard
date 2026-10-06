# ADR-0003: Append-only application audit history

- **Status:** Accepted
- **Date:** 2026-10-06
- **Decision owners:** LedgerGuard engineering

## Context

Auditors must reconstruct security-sensitive activity and business decisions from ingestion through case resolution. Ordinary application users must not be able to edit history, while operations still need controlled retention, backup, and recovery capabilities. Application logs are mutable/short-lived and are not sufficient evidence.

## Decision

- Store audit evidence in a dedicated `audit_events` table with a database-generated monotonic sequence, UUID public ID, UTC timestamp, actor, action, target, result, correlation IDs, and allowlisted before/after metadata.
- Grant the runtime application role `SELECT` and `INSERT`, but not `UPDATE` or `DELETE`, on audit events.
- Add a database trigger that rejects update/delete attempts, including accidental ORM writes. Migration/owner credentials remain separate from runtime credentials.
- Write the domain change and its audit event in the same database transaction whenever the action changes authoritative state.
- Record denied and failed security-sensitive actions even when no domain mutation commits, using a separate minimal audit transaction.
- Treat JSON snapshots as versioned, allowlisted, size-limited, and redacted. Never store passwords, password hashes, tokens, credentials, raw uploads, or unrestricted request bodies.
- Order an audit timeline by database `sequence_number`; preserve the original `occurred_at` to describe event time.
- Expose no update/delete audit endpoints. Auditor access is read-only and itself audited for security-sensitive views/exports.
- Retain events for an assumed minimum of seven years in the portfolio design. Only a separately privileged, explicitly approved retention process may remove expired partitions/rows, and it must emit durable retention evidence before deletion.

## Consequences

- Normal application compromise has a narrower path to alter audit history, though database-owner compromise remains a residual risk.
- Same-transaction writes prevent successful business mutations without their corresponding audit event.
- Failed requests need careful best-effort audit handling without leaking malicious payloads.
- The high-volume table needs indexes for target, actor, correlation, and time. Partitioning is deferred until Day 17 measurements justify it.
- Backups, database administration, and retention actions require operational audit controls beyond the application table; Day 16 and Day 19 will document them.

## Alternatives rejected

- **Application logs only:** retention, schema, access, and transaction coupling are insufficient for decision reconstruction.
- **Mutable history rows:** makes corrections indistinguishable from tampering; corrections should be new events.
- **Full global cryptographic hash chain:** adds write serialization and operational complexity. It may improve tamper evidence, but should be introduced only with a defined verification/export process and measured throughput impact.
- **Event sourcing for every domain aggregate:** provides history but materially increases implementation complexity beyond the product's needs; explicit history/evidence tables give a clearer version 1 boundary.
