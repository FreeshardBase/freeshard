from datetime import datetime
from typing import Optional

from pydantic import BaseModel

from portal_core.database.database import set_value, get_value
from portal_core.model.app_meta import PortalSize


class Profile(BaseModel):
	vm_id: str
	owner: Optional[str]
	owner_email: Optional[str]
	time_created: datetime
	time_assigned: datetime
	delete_after: Optional[datetime]
	portal_size: PortalSize
	max_portal_size: Optional[PortalSize]


def set_profile(profile: Profile):
	set_value('profile', profile.dict())


def get_profile() -> Profile:
	return Profile.parse_obj(get_value('profile'))
