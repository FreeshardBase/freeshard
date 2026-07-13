# DO NOT MODIFY - copied from freeshard-controller

import typing
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


class ParamSpec(BaseModel):
    """Describes one parameter a probe accepts, so a client can call it without guessing keys."""

    name: str
    required: bool
    type: str
    default: Any | None = None
    allowed: list[Any] | None = None  # bounded value set (Literal/enum)
    pattern: str | None = None
    minimum: int | None = None
    maximum: int | None = None


def describe_params(params_model: type[BaseModel]) -> list[ParamSpec]:
    """Derive a compact param schema from a probe's pydantic Params model."""
    specs: list[ParamSpec] = []
    for name, field in params_model.model_fields.items():
        annotation = field.annotation
        allowed: list[Any] | None = None
        if typing.get_origin(annotation) is typing.Literal:
            allowed = list(typing.get_args(annotation))
            type_name = type(allowed[0]).__name__ if allowed else "str"
        else:
            type_name = getattr(annotation, "__name__", str(annotation))
        pattern = minimum = maximum = None
        for meta in field.metadata:
            pattern = getattr(meta, "pattern", None) or pattern
            minimum = getattr(meta, "ge", None) if minimum is None else minimum
            maximum = getattr(meta, "le", None) if maximum is None else maximum
        specs.append(
            ParamSpec(
                name=name,
                required=field.is_required(),
                type=type_name,
                default=None if field.is_required() else field.default,
                allowed=allowed,
                pattern=pattern,
                minimum=minimum,
                maximum=maximum,
            )
        )
    return specs


class MenuEntry(BaseModel):
    name: str
    description: str
    required_level: int
    available: bool  # required_level <= diagnostic.level
    params: list[ParamSpec] = Field(default_factory=list)


class ProbeResult(BaseModel):
    name: str
    output: str
