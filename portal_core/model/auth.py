from enum import unique, Enum


class AuthValues:
	def __init__(self,
			x_ptl_client_type: str,
			x_ptl_client_id: str = None,
			x_ptl_client_name: str = None,
	):
		self.type = self.ClientType(x_ptl_client_type)
		self.id = x_ptl_client_id
		self.name = x_ptl_client_name

	@unique
	class ClientType(Enum):
		TERMINAL = 'terminal'
		PEER = 'peer'
		ANONYMOUS = 'anonymous'
