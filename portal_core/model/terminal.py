from pydantic import BaseModel

from portal_core.database.models import Icon


class InputTerminal(BaseModel):
	name: str
	icon: Icon = Icon.UNKNOWN


