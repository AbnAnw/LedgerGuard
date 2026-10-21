# Transaction Ingestion Schema v1.0

LedgerGuard accepts synthetic transaction batches through authenticated JSON and CSV endpoints. Administrators and operations analysts may ingest data; auditors are denied. Both formats use the same record validator and persistence path.

## Endpoints

- `POST /api/v1/ingestion/transactions/json` with an `application/json` body.
- `POST /api/v1/ingestion/transactions/csv` with multipart form fields and one UTF-8 CSV file.

Both require `Authorization: Bearer <session token>` and `Idempotency-Key: <key>`. A new request commits a durable job and returns HTTP 202; an exact retry returns the original job with HTTP 200 and `replayed: true`. Poll `GET /api/v1/jobs/{job_id}` for progress, failure evidence, and the terminal `ingestion_batch_id`. See [idempotency and data quality](IDEMPOTENCY_AND_DATA_QUALITY.md) and the [background-processing contract](../architecture/BACKGROUND_PROCESSING.md) for the complete retry and delivery rules.

## Batch metadata

| Field | Rules |
| --- | --- |
| `schema_version` | Required; exactly `1.0` |
| `source_system` | 1–80 characters; letters, digits, `.`, `_`, or `-`; must start with `synthetic-` while the repository's synthetic-only guard is enabled |
| `source_account_id` | 1–160 characters; letters, digits, `.`, `_`, `:`, `/`, or `-`; must identify an active account under `source_system` |
| `records` | JSON only; 1–10,000 objects |
| `file` | CSV only; UTF-8, configured default maximum 2,000,000 bytes, and 1–10,000 data rows; the multipart request also remains below the global body-size limit |

The CSV endpoint receives the three metadata values as form fields. CSV requires the seven non-optional record headers; `instrument_fingerprint` is an optional column.

## Record fields

| Field | Required | Rules |
| --- | :---: | --- |
| `source_record_id` | Yes | 1–200 characters using letters, digits, `.`, `_`, `:`, `/`, or `-` |
| `source_reference` | Yes | Same format and length as `source_record_id` |
| `amount` | Yes | Positive decimal **string**; up to 14 integer and 6 fractional digits; JSON numbers are rejected |
| `currency` | Yes | Uppercase allowlisted ISO 4217 code: `AUD`, `EUR`, `GBP`, `MVR`, `MYR`, `SGD`, or `USD` |
| `direction` | Yes | `debit` or `credit` |
| `status` | Yes | `pending`, `posted`, `voided`, or `reversed` |
| `occurred_at` | Yes | ISO 8601 string with `Z` or an explicit UTC offset; stored in UTC |
| `instrument_fingerprint` | No | Empty/null or 64 lowercase hexadecimal characters; never send a PAN or other raw instrument identifier |

Unpublished fields are rejected so schema changes remain explicit and versioned.

## Outcomes and evidence

Every syntactically readable row produces an `ingestion_records` row with its one-based row number, original payload, SHA-256 payload hash, outcome, stable reason codes, structured rejection details, and accepted transaction link when applicable. An all-valid batch is `completed`; a mixed or all-invalid batch is `completed_with_errors`.

The completed ingestion batch persists accepted, rejected, duplicate, and conflict totals; per-row outcomes; and a deterministic quality summary. The terminal job links to that batch. Rejected, duplicate, and conflicting records do not create financial transactions.

| Rejection code | Meaning |
| --- | --- |
| `MISSING_REQUIRED_FIELD` | A required record field is absent |
| `UNSUPPORTED_FIELD` | The row contains a field outside schema v1.0 |
| `INVALID_SOURCE_RECORD_ID` | Invalid source-record identifier |
| `INVALID_SOURCE_REFERENCE` | Invalid source reference |
| `INVALID_AMOUNT` | Non-string, non-positive, malformed, or excessive-precision amount |
| `INVALID_CURRENCY` | Currency is not an allowed uppercase code |
| `INVALID_DIRECTION` | Direction is outside the published values |
| `INVALID_STATUS` | Status is outside the published values |
| `INVALID_TIMESTAMP` | Timestamp is malformed or lacks an offset |
| `INVALID_INSTRUMENT_FINGERPRINT` | Fingerprint is not empty or 64 lowercase hex characters |
| `INVALID_RECORD` | Record-level schema failure without a more specific code |
| `DUPLICATE_SOURCE_RECORD` | The account already has the same normalized data under this source identifier |
| `CONFLICTING_SOURCE_RECORD` | The account already has different normalized data under this source identifier |

Batch-level errors include `ACCOUNT_NOT_FOUND`, `IDEMPOTENCY_KEY_REUSED`, `INVALID_CSV_ENCODING`, `MISSING_CSV_COLUMNS`, `EMPTY_BATCH`, `BATCH_TOO_LARGE`, and `UPLOAD_TOO_LARGE`.

## Scope boundary

Day 6 requires client idempotency keys and classifies duplicate/conflicting source identifiers before a financial fact is written. Day 9 runs CSV parsing and row processing in Celery while retaining the same schema and financial invariants.

Synthetic examples are under [`sample-data/`](../../sample-data/README.md).
