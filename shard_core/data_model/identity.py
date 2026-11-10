from typing import Optional

from pydantic import BaseModel, computed_field

from shard_core.service import crypto
from shard_core.settings import settings


class Identity(BaseModel):
    id: str
    name: str
    description: Optional[str] = None
    private_key: str
    is_default: bool = False

    def __str__(self):
        return f"Identity[{self.short_id}, {self.name}]"

    @classmethod
    def create(cls, name: str, description: str = None) -> "Identity":
        private_key = crypto.PrivateKey()
        return Identity(
            id=private_key.get_public_key().to_hash_id(),
            name=name,
            description=description,
            private_key=private_key.to_bytes().decode(),
        )

    @computed_field
    @property
    def short_id(self) -> str:
        return self.id[0:6]

    @property
    def public_key(self) -> crypto.PublicKey:
        return crypto.PrivateKey(self.private_key).get_public_key()

    @computed_field
    @property
    def public_key_pem(self) -> str:
        return self.public_key.to_bytes().decode()

    @computed_field
    @property
    def domain(self) -> str:
        dns = settings().dns
        subdomain = self.id[: dns.prefix_length].lower()
        domain = f"{subdomain}.{dns.zone}"
        return domain


class SafeIdentity(BaseModel):
    domain: str
    id: str
    public_key_pem: str
    # The shard owner's verified email (users.email), for templates that want
    # it alongside the other portal facts. None whenever no owner exists yet,
    # or the owner has no verified address (unset, or still pending
    # confirmation) — never an empty string, so a Jinja template can branch on
    # it cleanly. Not populated by the other two callers of from_identity
    # (traefik config compilation, the auth cache); it only matters for
    # docker-compose template rendering.
    owner_email: Optional[str] = None

    @computed_field
    @property
    def short_id(self) -> str:
        return self.id[:6]

    @classmethod
    def from_identity(cls, identity: Identity, owner_email: Optional[str] = None):
        return cls(
            domain=identity.domain,
            id=identity.id,
            public_key_pem=identity.public_key_pem,
            owner_email=owner_email,
        )


class OutputIdentity(BaseModel):
    id: str
    name: str
    description: Optional[str] = None
    is_default: bool
    public_key_pem: str
    domain: str


class InputIdentity(BaseModel):
    id: Optional[str] = None
    name: Optional[str] = ""
    description: Optional[str] = ""
