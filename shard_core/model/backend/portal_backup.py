# DO NOT MODIFY - copied from portal_controller

from pydantic import BaseModel


class SasUrlResponse(BaseModel):
	sas_url: str
	container_name: str
