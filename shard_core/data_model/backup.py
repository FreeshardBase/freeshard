import datetime
from typing import List

from pydantic import BaseModel


class BackupStats(BaseModel):
    directory: str
    startTime: datetime.datetime
    endTime: datetime.datetime
    rclone_stats: dict


class BackupReport(BaseModel):
    directories: List[BackupStats]
    startTime: datetime.datetime
    endTime: datetime.datetime


class BackupPassphraseResponse(BaseModel):
    passphrase: str


class BackupPassphraseLastAccessInfoDB(BaseModel):
    time: datetime.datetime
    terminal_id: str


class BackupPassphraseLastAccessInfoResponse(BackupPassphraseLastAccessInfoDB):
    terminal_name: str


class BackupInfoResponse(BaseModel):
    last_report: BackupReport | None
    last_passphrase_access_info: BackupPassphraseLastAccessInfoResponse | None
