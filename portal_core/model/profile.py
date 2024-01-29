from datetime import datetime
from typing import Optional

from pydantic import BaseModel

from portal_core.database.database import set_value, get_value
from portal_core.model.app_meta import PortalSize
from portal_core.model.backend.portal_meta import PortalMetaExt


class Profile(BaseModel):
	vm_id: str
	owner: Optional[str]
	owner_email: Optional[str]
	time_created: datetime
	time_assigned: datetime
	delete_after: Optional[datetime]
	portal_size: PortalSize
	max_portal_size: Optional[PortalSize]

	@classmethod
	def from_portal(cls, portal: PortalMetaExt):
		return cls(
			vm_id=portal.id,
			owner=portal.owner,
			owner_email=portal.owner_email,
			time_created=portal.time_created,
			time_assigned=portal.time_assigned,
			delete_after=portal.delete_after,
			portal_size=portal.size,
			max_portal_size=portal.max_size,
		)


def set_profile(profile: Profile):
	set_value('profile', profile.dict())


def get_profile() -> Profile:
	return Profile.parse_obj(get_value('profile'))
