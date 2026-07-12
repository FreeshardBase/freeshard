# DO NOT MODIFY - copied from freeshard-controller

import uuid
from datetime import datetime
from enum import StrEnum, auto
from typing import Any

from pydantic import BaseModel, Field


class DiagnosticStatus(StrEnum):
    ACTIVE = auto()
    CLOSED = auto()
    EXPIRED = auto()


class DiagnosticEventType(StrEnum):
    PROBE = auto()
    NOTE = auto()
    PROMOTE = auto()


MIN_LEVEL = 1
MAX_LEVEL = 3


class DiagnosticEvent(BaseModel):
    timestamp: datetime
    event_type: DiagnosticEventType
    payload: dict[str, Any]


class DiagnosticDb(BaseModel):
    id: uuid.UUID
    shard_id: int
    opened_by: int
    level: int
    status: DiagnosticStatus
    opened_at: datetime
    expires_at: datetime
    closed_at: datetime | None = None
    findings: str | None = None


class DiagnosticResponse(DiagnosticDb):
    events: list[DiagnosticEvent] = Field(default_factory=list)


class OpenDiagnosticRequest(BaseModel):
    level: int = Field(ge=MIN_LEVEL, le=MAX_LEVEL)
    ttl_minutes: int = Field(ge=1, le=720)


class PromoteRequest(BaseModel):
    level: int = Field(ge=MIN_LEVEL, le=MAX_LEVEL)


class NoteRequest(BaseModel):
    text: str = Field(min_length=1, max_length=4000)


class FindingsRequest(BaseModel):
    markdown: str = Field(min_length=1)


class ProbeRequest(BaseModel):
    name: str
    params: dict[str, Any] = Field(default_factory=dict)


class MenuEntry(BaseModel):
    name: str
    description: str
    required_level: int
    available: bool  # required_level <= diagnostic.level


class ProbeResult(BaseModel):
    name: str
    output: str
