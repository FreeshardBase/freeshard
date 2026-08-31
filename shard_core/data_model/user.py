from datetime import datetime
from enum import Enum
from typing import Optional

from email_validator import validate_email, EmailNotValidError
from pydantic import BaseModel, Field, field_validator


class Role(str, Enum):
    # Keep in sync with the user_role enum in migrations/shard-core-0002-users.sql
    OWNER = "owner"
    MEMBER = "member"


class User(BaseModel):
    id: int
    username: str
    display_name: str
    email: Optional[str] = None
    pending_email: Optional[str] = None
    email_token_hash: Optional[str] = None
    email_token_expires: Optional[datetime] = None
    role: Role = Role.MEMBER
    disabled: bool = False
    created: Optional[datetime] = None

    def __str__(self):
        return f"User[{self.id}, {self.username}]"


class OutputUser(BaseModel):
    id: int
    username: str
    display_name: str
    email: Optional[str] = None
    pending_email: Optional[str] = None
    role: Role

    @classmethod
    def from_user(cls, user: User) -> "OutputUser":
        return cls(**user.model_dump())


class InputUser(BaseModel):
    display_name: Optional[str] = Field(default=None, max_length=200)
    email: Optional[str] = Field(default=None, max_length=254)

    @field_validator("email")
    @classmethod
    def validate_email(cls, v):
        """Reject anything that is not an address; `null` is how you clear one.

        An empty string is a rejection, not a clear — a form that blanks its
        field must not take the notify-then-clear path by accident.
        """
        if v is None:
            return None
        try:
            # No deliverability check: it is a blocking DNS query on the event
            # loop, and an MX record says nothing about who reads the mailbox.
            validated = validate_email(
                v, check_deliverability=False, allow_smtputf8=False
            )
        except EmailNotValidError as e:
            raise ValueError(f"invalid email: {e}") from e
        # the normalized form is what gets asserted as verified to third
        # parties, so store that rather than whatever casing was typed
        return validated.normalized
