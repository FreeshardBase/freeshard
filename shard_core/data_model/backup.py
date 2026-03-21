import datetime
from typing import List

from pydantic import BaseModel


class BackupStats(BaseModel):
    directory: str
    startTime: datetime.datetime
    endTime: datetime.datetime
    bytes: int | None = None
    checks: int | None = None
    deletedDirs: int | None = None
    deletes: int | None = None
    elapsedTime: float | None = None
    errors: int | None = None
    fatalError: bool | None = None
    renames: int | None = None
    retryError: bool | None = None
    serverSideCopies: int | None = None
    serverSideCopyBytes: int | None = None
    serverSideMoveBytes: int | None = None
    serverSideMoves: int | None = None
    speed: int | None = None
    totalBytes: int | None = None
    totalChecks: int | None = None
    totalTransfers: int | None = None
    transferTime: float | None = None
    transfers: int | None = None


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
