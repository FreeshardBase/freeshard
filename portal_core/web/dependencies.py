from enum import Enum, unique

from fastapi import Header


class AuthValues:
	def __init__(self,
			x_ptl_client_type: str = Header(None),
			x_ptl_client_id: str = Header(None),
			x_ptl_client_name: str = Header(None),
	):
		self.type = self.ClientType(x_ptl_client_type) if x_ptl_client_type else self.ClientType.ANONYMOUS
		self.id = x_ptl_client_id
		self.name = x_ptl_client_name

	@unique
	class ClientType(Enum):
		TERMINAL = 'terminal'
		PEER = 'peer'
		ANONYMOUS = 'anonymous'
