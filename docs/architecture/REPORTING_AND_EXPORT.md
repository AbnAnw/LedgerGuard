# Reporting and export contract

## Purpose and trust boundary

LedgerGuard reports are read-only projections over authoritative PostgreSQL facts. They do not
copy financial state into a reporting store. The API requires `reports:read`, uses explicit UTC
cutoffs and account scope, returns monetary values as six-place decimal strings, and records every
view or export in append-only audit history.

Day 13 provides:

- a daily reconciliation summary for one source account and one UTC calendar date; and
- a current unresolved-case report containing cases created at or before an explicit UTC cutoff.

Administrators, operations analysts, and auditors may read and export these reports. Report routes
do not grant any mutation permission.

## Daily reconciliation summary

The caller supplies `report_date`, `source_system`, and `source_account_id`. The date maps to the
half-open UTC interval `[00:00:00, next day 00:00:00)`. Eligible transaction totals include posted
transactions by `occurred_at`; eligible settlement totals include confirmed settlements by
`settled_at`. Values are grouped by currency and never converted across currencies.

The report also includes the latest completed reconciliation run whose input cutoff is before the
end of the requested day. Its classification counts and totals are labelled as a reconciliation
snapshot and are not added to the source-fact totals, because candidate groups can repeat economic
facts. An absent run is represented as `null`, not as an invented zero-result run.

For every currency, LedgerGuard computes totals twice:

1. it loads individual eligible values and sums them with Python `Decimal`; and
2. it executes independent PostgreSQL `COUNT`/`SUM` groupings over the same scope.

The count, currency set, and exact decimal sum must agree. Any mismatch fails closed with HTTP 503
and `REPORT_TOTAL_MISMATCH`; LedgerGuard does not return or export an unverified report.

## Unresolved-case report

The caller supplies an offset-aware `cutoff_at`, normalized to UTC. The report includes current
cases whose status is not `resolved` and whose creation time is at or before that cutoff. This is a
current operational queue constrained by age; it is not described as a historical status snapshot.
Each row explicitly includes case identity, title, current status and priority, owner identity,
creation time, age at cutoff, linked-alert count, and distinct rule codes.

Resolved cases are excluded. Future-created cases, negative ages, comments, resolution narratives,
and unrestricted alert evidence are never exported.

## CSV safety and explicit fields

CSV exports use fixed server-side column lists and filenames. They never serialize arbitrary model
dictionaries or client-selected columns. Every cell is passed through one neutralizer before the
standard CSV writer handles quoting. If the first non-whitespace character is `=`, `+`, `-`, or
`@`, or the value begins with a tab, carriage return, or line feed, LedgerGuard prefixes an
apostrophe. This prevents spreadsheet software from interpreting user-controlled text or signed
values as formulas.

The response declares UTF-8 CSV, uses CRLF rows, and returns a fixed attachment filename. JSON and
CSV are built from the same verified report object so their totals cannot diverge.

## Edge cases

- A missing or inactive account returns HTTP 404.
- Naive timestamps and malformed scope identifiers fail input validation.
- A date with no eligible facts returns an empty currency list and `totals_verified: true` after
  both calculations independently agree on zero rows.
- Currencies present on only one side receive an exact zero count and `0.000000` total on the other.
- Duplicate reconciliation runs do not multiply source-fact totals; only one latest snapshot is
  displayed.
- A report-total mismatch returns no partial JSON or CSV.
- Empty unresolved queues export the header only.
- Titles beginning with formula-control characters are preserved visibly but neutralized in CSV.

## Tests and acceptance criteria

Automated tests cover decimal aggregation, independent-total agreement and mismatch, empty and
single-sided currencies, formula neutralization, fixed CSV headers, UTC validation, all supported
role reads, unsupported-role denial, report audit events, and interface loading/empty/error/export
states.

Day 13 is complete when:

1. JSON and CSV daily summaries agree with independently queried transaction and settlement totals;
2. unresolved cases are cutoff-bounded and exclude resolved cases;
3. unsafe spreadsheet cells are neutralized and only documented fields are exported;
4. report views and exports create structured audit events; and
5. administrators, analysts, and auditors can use the interface while unsupported roles are denied.
