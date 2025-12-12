# DO NOT MODIFY - copied from freeshard-controller

from datetime import datetime
from enum import StrEnum, auto

from pydantic import BaseModel

from .shard_model import Cloud


# noinspection PyEnum
class SettingKey(StrEnum):
    MIN_NR_OF_STANDBY_SHARDS = auto()


class Setting(BaseModel):
    key: SettingKey
    value: str | bool | int | float
    type: str
    updated_at: datetime
    cloud: str | None = None

    def __str__(self) -> str:
        if self.type != "str":
            raise ValueError("Setting is not of type str")
        return str(self.value)

    def __bool__(self) -> bool:
        if self.type != "bool":
            raise ValueError("Setting is not of type bool")
        return bool(self.value)

    def __int__(self) -> int:
        if self.type != "int":
            raise ValueError("Setting is not of type int")
        return int(self.value)

    def __float__(self) -> float:
        if self.type != "float":
            raise ValueError("Setting is not of type float")
        return float(self.value)


class SettingUpdate(BaseModel):
    key: SettingKey
    value: str | bool | int | float
    cloud: Cloud
