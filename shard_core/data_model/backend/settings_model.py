# DO NOT MODIFY - copied from freeshard-controller

from datetime import datetime
from enum import Enum, StrEnum, auto
from functools import lru_cache
from typing import Annotated, Any

import annotated_types
import pydantic
from pydantic import BaseModel, Field, TypeAdapter
from pydantic.fields import FieldInfo

from .shard_model import Cloud, VmSize


# noinspection PyEnum
class SettingKey(StrEnum):
    MIN_NR_OF_STANDBY_SHARDS = auto()
    NEW_INSTANCE_SIZE = auto()
    NEW_INSTANCE_IMAGE = auto()
    AUTO_PROVISIONING_ENABLED = auto()
    NEW_SHARD_CORE_VERSION = auto()
    TRIAL_MAX_VM_SIZE = auto()
    SUBSCRIBED_MAX_VM_SIZE = auto()


class SettingsSpec(BaseModel):
    """The single place a setting's type lives. Never instantiated: field names are the
    `SettingKey` values, and the schema endpoint, the write validation and the read cast
    all derive from these annotations."""

    min_nr_of_standby_shards: int = Field(ge=0)
    new_instance_size: VmSize
    trial_max_vm_size: VmSize
    subscribed_max_vm_size: VmSize
    auto_provisioning_enabled: bool
    new_shard_core_version: str
    new_instance_image: str


PER_CLOUD_KEYS = frozenset({SettingKey.NEW_INSTANCE_IMAGE})
"""Keys that cannot have a `Cloud.DEFAULT` row. An image identifier is namespaced by its
provider, so there is nothing a cloud without its own row could fall back to."""


# noinspection PyEnum
class SettingScope(StrEnum):
    GLOBAL = auto()
    PER_CLOUD = auto()


class SettingValueInvalid(ValueError):
    """A value does not match its key's declared type."""


class SettingSchemaEntry(BaseModel):
    """One row of the settings matrix, as the client needs it. Flat rather than raw JSON
    Schema so the generated TypeScript carries a real type instead of an opaque object."""

    key: SettingKey
    value_type: str
    options: list[str] | None = None
    ge: float | None = None
    le: float | None = None
    scope: SettingScope = SettingScope.GLOBAL


class Setting(BaseModel):
    key: SettingKey
    value: str | bool | int | float
    updated_at: datetime
    cloud: str | None = None


class SettingUpdate(BaseModel):
    key: SettingKey
    value: str | bool | int | float
    cloud: Cloud


def setting_scope(key: SettingKey) -> SettingScope:
    return SettingScope.PER_CLOUD if key in PER_CLOUD_KEYS else SettingScope.GLOBAL


def setting_schema_entry(key: SettingKey) -> SettingSchemaEntry:
    field = _field(key)
    annotation = field.annotation
    is_enum = isinstance(annotation, type) and issubclass(annotation, Enum)
    return SettingSchemaEntry(
        key=key,
        value_type="str" if is_enum else annotation.__name__,
        options=[str(member.value) for member in annotation] if is_enum else None,
        ge=next((m.ge for m in field.metadata if isinstance(m, annotated_types.Ge)), None),
        le=next((m.le for m in field.metadata if isinstance(m, annotated_types.Le)), None),
        scope=setting_scope(key),
    )


def validate_setting_value(key: SettingKey, value: Any) -> str | bool | int | float:
    """Coerce a raw value to the key's declared type, or raise `SettingValueInvalid`."""
    try:
        return _adapter(key).validate_python(value)
    except pydantic.ValidationError as e:
        raise SettingValueInvalid(f"{key}: {'; '.join(err['msg'] for err in e.errors())}") from e


def _field(key: SettingKey) -> FieldInfo:
    return SettingsSpec.model_fields[key.value]


@lru_cache
def _adapter(key: SettingKey) -> TypeAdapter:
    """Validating one field on its own needs `Annotated[annotation, field]`: the field is
    what carries `ge=0`, so dropping it would type-check the value and skip the bound."""
    field = _field(key)
    return TypeAdapter(Annotated[field.annotation, field])
