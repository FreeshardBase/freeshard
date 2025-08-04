# DO NOT MODIFY - copied from freeshard-controller

from pydantic import BaseModel


class Health(BaseModel):
    status: str
