import datetime
from typing import List

from pydantic import BaseModel


class BackupStats(BaseModel):
	directory: str
	startTime: datetime.datetime
	endTime: datetime.datetime
	bytes: int
	checks: int
	deletedDirs: int
	deletes: int
	elapsedTime: float
	errors: int
	fatalError: bool
	renames: int
	retryError: bool
	serverSideCopies: int
	serverSideCopyBytes: int
	serverSideMoveBytes: int
	serverSideMoves: int
	speed: int
	totalBytes: int
	totalChecks: int
	totalTransfers: int
	transferTime: float
	transfers: int


class BackupReport(BaseModel):
	directories: List[BackupStats]
	startTime: datetime.datetime
	endTime: datetime.datetime


class BackupPassphraseResponse(BaseModel):
	passphrase: str


class BackupPassphraseLastAccessInfo(BaseModel):
	time: datetime.datetime
	ip: str
	terminal_id: str


class BackupInfoResponse(BaseModel):
	last_report: BackupReport | None
	last_passphrase_access_info: BackupPassphraseLastAccessInfo | None
