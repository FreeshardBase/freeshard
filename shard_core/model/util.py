from typing import Dict, Any

from pydantic import BaseModel


class PropertyBaseModel(BaseModel):
	"""
	Workaround for serializing properties with pydantic until
	https://github.com/samuelcolvin/pydantic/issues/935
	is solved
	See also:
		https://stackoverflow.com/questions/63264888/pydantic-using-property-getter-decorator-for-a-field-with-an-alias
	"""

	@classmethod
	def get_properties(cls):
		c = cls.Config
		fields = getattr(c, 'fields', {})
		return [prop for prop in dir(cls) if
			isinstance(getattr(cls, prop), property)
			and prop not in ("__values__", "fields")
			and (prop not in fields or 'exclude' not in fields[prop] or not fields[prop]['exclude'])
		]

	def dict(self, *args, **kwargs) -> Dict[str, Any]:
		attribs = super().dict(*args, **kwargs)
		props = self.get_properties()

		# Update the attribute dict with the properties
		if props:
			attribs.update({prop: getattr(self, prop) for prop in props})

		return attribs
