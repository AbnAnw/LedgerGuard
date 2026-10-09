# Entity-Relationship Diagram

This logical ER diagram shows ownership and evidence flow. Column-level types, constraints, lifecycle rules, and indexes are defined in [the data model](DATA_MODEL.md).

```mermaid
erDiagram
    USERS {
        uuid id PK
        citext email UK
        string status
        timestamptz created_at
        int version
    }
    ROLES {
        string code PK
        string description
    }
    USER_ROLES {
        uuid id PK
        uuid user_id FK
        string role_code FK
        uuid granted_by_user_id FK
        timestamptz revoked_at
    }
    AUTH_SESSIONS {
        uuid id PK
        uuid user_id FK
        string token_digest UK
        timestamptz created_at
        timestamptz expires_at
        timestamptz revoked_at
    }
    ACCOUNTS {
        uuid id PK
        string source_system
        string source_account_id
        string status
        int version
    }
    INGESTION_BATCHES {
        uuid id PK
        string record_kind
        string idempotency_key UK
        string payload_sha256
        string status
        uuid requested_by_user_id FK
        uuid correlation_id
    }
    INGESTION_RECORDS {
        uuid id PK
        uuid batch_id FK
        int row_number
        string outcome
        uuid transaction_id FK
        uuid settlement_id FK
    }
    TRANSACTIONS {
        uuid id PK
        uuid account_id FK
        uuid batch_id FK
        string source_record_id
        decimal amount
        string currency
        timestamptz occurred_at
        uuid reversal_of_transaction_id FK
    }
    SETTLEMENTS {
        uuid id PK
        uuid account_id FK
        uuid batch_id FK
        string source_record_id
        decimal amount
        string currency
        timestamptz settled_at
    }
    RECONCILIATION_RUNS {
        uuid id PK
        uuid account_id FK
        string algorithm_version
        timestamptz input_cutoff_at
        string replay_key UK
        string status
        uuid requested_by_user_id FK
    }
    RECONCILIATION_RESULTS {
        uuid id PK
        uuid run_id FK
        string classification
        string reason_code
        decimal difference_amount
        string evidence_sha256
        string review_status
    }
    RECONCILIATION_RESULT_TRANSACTIONS {
        uuid result_id PK,FK
        uuid transaction_id PK,FK
        string item_role
        decimal allocated_amount
    }
    RECONCILIATION_RESULT_SETTLEMENTS {
        uuid result_id PK,FK
        uuid settlement_id PK,FK
        string item_role
        decimal allocated_amount
    }
    FRAUD_RULES {
        uuid id PK
        string code UK
        uuid created_by_user_id FK
        int version
    }
    FRAUD_RULE_VERSIONS {
        uuid id PK
        uuid rule_id FK
        int version_number
        string rule_type
        string status
        uuid created_by_user_id FK
    }
    ALERTS {
        uuid id PK
        uuid rule_version_id FK
        uuid transaction_id FK
        uuid reconciliation_result_id FK
        string deduplication_key UK
        string severity
        string status
    }
    CASES {
        uuid id PK
        bigint case_number UK
        string status
        string priority
        uuid owner_user_id FK
        uuid created_by_user_id FK
        int version
    }
    CASE_ALERTS {
        uuid case_id PK,FK
        uuid alert_id PK,FK
        uuid linked_by_user_id FK
        timestamptz linked_at
    }
    CASE_COMMENTS {
        uuid id PK
        uuid case_id FK
        uuid author_user_id FK
        text body
        timestamptz created_at
    }
    CASE_STATUS_HISTORY {
        uuid id PK
        uuid case_id FK
        string from_status
        string to_status
        uuid changed_by_user_id FK
        uuid correlation_id
    }
    AUDIT_EVENTS {
        bigint sequence_number PK
        uuid id UK
        uuid actor_user_id FK
        string action
        string target_type
        uuid target_id
        string result
        uuid correlation_id
        timestamptz occurred_at
    }

    USERS ||--o{ USER_ROLES : receives
    USERS ||--o{ AUTH_SESSIONS : authenticates
    ROLES ||--o{ USER_ROLES : grants
    USERS ||--o{ USER_ROLES : administers
    USERS ||--o{ INGESTION_BATCHES : requests
    USERS ||--o{ RECONCILIATION_RUNS : requests
    USERS ||--o{ FRAUD_RULES : creates
    USERS ||--o{ FRAUD_RULE_VERSIONS : authors
    USERS ||--o{ CASES : owns_or_creates
    USERS ||--o{ CASE_COMMENTS : authors
    USERS ||--o{ CASE_STATUS_HISTORY : changes
    USERS ||--o{ AUDIT_EVENTS : acts

    ACCOUNTS ||--o{ TRANSACTIONS : contains
    ACCOUNTS ||--o{ SETTLEMENTS : contains
    ACCOUNTS ||--o{ RECONCILIATION_RUNS : scopes

    INGESTION_BATCHES ||--o{ INGESTION_RECORDS : reports
    INGESTION_BATCHES ||--o{ TRANSACTIONS : accepts
    INGESTION_BATCHES ||--o{ SETTLEMENTS : accepts
    INGESTION_RECORDS o|--o| TRANSACTIONS : materializes
    INGESTION_RECORDS o|--o| SETTLEMENTS : materializes
    TRANSACTIONS o|--o{ TRANSACTIONS : reverses

    RECONCILIATION_RUNS ||--o{ RECONCILIATION_RESULTS : produces
    RECONCILIATION_RESULTS ||--o{ RECONCILIATION_RESULT_TRANSACTIONS : includes
    TRANSACTIONS ||--o{ RECONCILIATION_RESULT_TRANSACTIONS : participates
    RECONCILIATION_RESULTS ||--o{ RECONCILIATION_RESULT_SETTLEMENTS : includes
    SETTLEMENTS ||--o{ RECONCILIATION_RESULT_SETTLEMENTS : participates

    FRAUD_RULES ||--|{ FRAUD_RULE_VERSIONS : versions
    FRAUD_RULE_VERSIONS ||--o{ ALERTS : triggers
    TRANSACTIONS o|--o{ ALERTS : evidenced_by
    RECONCILIATION_RESULTS o|--o{ ALERTS : evidenced_by

    CASES ||--o{ CASE_ALERTS : investigates
    ALERTS ||--o{ CASE_ALERTS : linked_to
    CASES ||--o{ CASE_COMMENTS : discusses
    CASES ||--|{ CASE_STATUS_HISTORY : transitions
```

## Relationship notes

- The two reconciliation item tables avoid unenforceable polymorphic foreign keys and support multiple matched or candidate facts per result.
- `ingestion_records` links to at most one materialised fact. Invalid/duplicate/conflicting rows keep their evidence without creating a financial fact.
- Rule versions, alerts, reconciliation results, comments, history, and audit events retain immutable evidence. Mutable aggregate summaries use optimistic concurrency.
- `audit_events.target_type/target_id` is intentionally a logical reference: a single audit table can cover authentication attempts that have no target row and future entities without a polymorphic database foreign key.
- The diagram omits repeated actor and reviewer relationships for readability; the detailed model remains authoritative.
