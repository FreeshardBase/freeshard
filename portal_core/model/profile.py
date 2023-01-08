from datetime import datetime
from typing import Optional

from pydantic import BaseModel


class Profile(BaseModel):
	vm_id: str
	owner: Optional[str]
	owner_email: Optional[str]
	time_created: datetime
	time_assigned: datetime
	delete_after: Optional[datetime]
	portal_size: str
