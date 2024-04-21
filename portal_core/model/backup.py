import datetime
from typing import List

from pydantic import BaseModel


class BackupStats(BaseModel):
	directory: str
	startTime: datetime.datetime
	endTime: datetime.datetime
	bytes: int | None
	checks: int | None
	deletedDirs: int | None
	deletes: int | None
	elapsedTime: float | None
	errors: int | None
	fatalError: bool | None
	renames: int | None
	retryError: bool | None
	serverSideCopies: int | None
	serverSideCopyBytes: int | None
	serverSideMoveBytes: int | None
	serverSideMoves: int | None
	speed: int | None
	totalBytes: int | None
	totalChecks: int | None
	totalTransfers: int | None
	transferTime: float | None
	transfers: int | None


class BackupReport(BaseModel):
	directories: List[BackupStats]
	startTime: datetime.datetime
	endTime: datetime.datetime


class BackupPassphraseResponse(BaseModel):
	passphrase: str


class BackupPassphraseLastAccessInfo(BaseModel):
	time: datetime.datetime
	terminal_id: str


class BackupInfoResponse(BaseModel):
	last_report: BackupReport | None
	last_passphrase_access_info: BackupPassphraseLastAccessInfo | None
