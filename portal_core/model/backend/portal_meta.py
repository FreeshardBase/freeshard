# DO NOT MODIFY - copied from portal_controller

from datetime import datetime
from enum import Enum
from typing import List

from pydantic import BaseModel

from .permissions import PermissionHolder


class Size(str, Enum):
	XS = 'xs'
	S = 's'
	M = 'm'
	L = 'l'
	XL = 'xl'


class AppUsageReport(BaseModel):
	id: str
	portal_id: str
	year: int
	month: int
	usage: dict[str, int]
	assigned_amount: int | None = None


class AppUsageReportUpdate(BaseModel):
	assigned_amount: int | None = None


class PortalMetaBase(PermissionHolder, BaseModel):
	id: str
	hash_id: str | None = None
	domain: str | None = None
	from_image: str
	address: str | None = None
	public_key_pem: str | None = None
	status: str
	owner: str | None = None
	owner_email: str | None = None
	size: Size
	max_size: Size | None = None
	time_created: datetime
	time_assigned: datetime | None = None
	expiration_warning_24h_sent: datetime | None = None
	expiration_warning_1h_sent: datetime | None = None
	delete_after: datetime | None = None
	context: dict | None = None


class PortalMetaExt(PortalMetaBase):
	app_usage_reports: List[AppUsageReport] | None = None


class PortalMetaDb(PortalMetaExt):
	shared_secret: str | None = None


class PortalMetaListItem(BaseModel):
	machine_id: str
	hash_id: str | None
	domain: str | None
	status: str
	owner_name: str | None
	owner_email: str | None


class PortalMetaUpdate(BaseModel):
	owner: str | None = None
	max_size: Size | None = None
	delete_after: datetime | None = None
