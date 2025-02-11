from datetime import datetime
from typing import Optional

from pydantic import BaseModel

from shard_core.database.database import set_value, get_value
from shard_core.model.app_meta import VMSize
from shard_core.model.backend.portal_meta import PortalMetaExt


class Profile(BaseModel):
	vm_id: str
	owner: Optional[str]
	owner_email: Optional[str]
	time_created: datetime
	time_assigned: Optional[datetime]
	delete_after: Optional[datetime]
	vm_size: VMSize
	max_vm_size: Optional[VMSize]

	@classmethod
	def from_portal(cls, portal: PortalMetaExt):
		return cls(
			vm_id=portal.id,
			owner=portal.owner,
			owner_email=portal.owner_email,
			time_created=portal.time_created,
			time_assigned=portal.time_assigned,
			delete_after=portal.delete_after,
			vm_size=VMSize(portal.size),
			max_vm_size=VMSize(portal.max_size),
		)


def set_profile(profile: Profile):
	set_value('profile', profile.dict())


def get_profile() -> Profile:
	return Profile.parse_obj(get_value('profile'))
