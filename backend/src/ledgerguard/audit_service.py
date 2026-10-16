"""Shared append-only, redacted audit event writer."""

from __future__ import annotations

import json
import re
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy.orm import Session

from ledgerguard.models import AuditActorType, AuditEvent, AuditResult

ACTION_PATTERN = re.compile(r"^[a-z][a-z0-9_.]{2,99}$")
TARGET_PATTERN = re.compile(r"^[a-z][a-z0-9_]{1,79}$")
FORBIDDEN_KEYS = frozenset(
    {
        "password",
        "password_hash",
        "token",
        "access_token",
        "authorization",
        "credential",
        "credentials",
        "secret",
        "raw_upload",
        "csv_content",
        "payload",
    }
)
MAX_STATE_BYTES = 16_384
MAX_METADATA_BYTES = 8_192


def _validate_json_object(value: dict[str, Any] | None, *, field: str, maximum_bytes: int) -> None:
    if value is None:
        return
    stack: list[object] = [value]
    while stack:
        current = stack.pop()
        if isinstance(current, dict):
            for key, child in current.items():
                if key.lower() in FORBIDDEN_KEYS:
                    raise ValueError(f"{field} contains forbidden key: {key}")
                stack.append(child)
        elif isinstance(current, list):
            stack.extend(current)
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    if len(encoded.encode("utf-8")) > maximum_bytes:
        raise ValueError(f"{field} exceeds its audit size limit")


def append_audit_event(
    db: Session,
    *,
    action: str,
    target_type: str,
    actor_user_id: UUID | None,
    result: AuditResult = AuditResult.SUCCESS,
    correlation_id: UUID | None = None,
    request_id: UUID | None = None,
    job_id: UUID | None = None,
    target_id: UUID | None = None,
    before_state: dict[str, Any] | None = None,
    after_state: dict[str, Any] | None = None,
    metadata: dict[str, Any] | None = None,
) -> AuditEvent:
    """Validate and stage one audit event in the caller's transaction."""

    if not ACTION_PATTERN.fullmatch(action):
        raise ValueError("audit action must use a stable lower-case dotted name")
    if not TARGET_PATTERN.fullmatch(target_type):
        raise ValueError("audit target_type must use a stable lower-case name")
    event_metadata = metadata or {"schema_version": "audit-v1"}
    _validate_json_object(before_state, field="before_state", maximum_bytes=MAX_STATE_BYTES)
    _validate_json_object(after_state, field="after_state", maximum_bytes=MAX_STATE_BYTES)
    _validate_json_object(event_metadata, field="metadata", maximum_bytes=MAX_METADATA_BYTES)
    event = AuditEvent(
        actor_user_id=actor_user_id,
        actor_type=AuditActorType.USER if actor_user_id is not None else AuditActorType.ANONYMOUS,
        action=action,
        target_type=target_type,
        target_id=target_id,
        result=result,
        correlation_id=correlation_id or uuid4(),
        request_id=request_id,
        job_id=job_id,
        before_state=before_state,
        after_state=after_state,
        event_metadata=event_metadata,
    )
    db.add(event)
    return event
