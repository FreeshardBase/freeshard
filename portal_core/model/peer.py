from pydantic import BaseModel, field_validator


class InputPeer(BaseModel):
	id: str
	name: str | None = None

	@field_validator('id')
	def must_be_long_enough(cls, v):
		if len(v) < 6:
			raise ValueError(f'{v} is too short, must be at least 6 characters')
		return v
