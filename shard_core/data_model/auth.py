from enum import unique, Enum


class AuthState:
    def __init__(
        self,
        x_ptl_client_type: str,
        x_ptl_client_id: str = None,
        x_ptl_client_name: str = None,
    ):
        self.type = self.ClientType(x_ptl_client_type)
        self.id = x_ptl_client_id
        self.name = x_ptl_client_name

    def __str__(self):
        if self.type == self.ClientType.ANONYMOUS:
            return self.type.value
        else:
            return f"AuthState {self.type.value}: {self.id} ({self.name})"

    @unique
    class ClientType(Enum):
        TERMINAL = "terminal"
        PEER = "peer"
        ANONYMOUS = "anonymous"

    @property
    def header_values(self):
        return {
            "client_type": self.type.value,
            "client_id": self.id or "",
            "client_name": self.name or "",
        }
