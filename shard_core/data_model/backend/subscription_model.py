# DO NOT MODIFY - copied from freeshard-controller

from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel


class SubscriptionStatus(StrEnum):
    ACTIVE = "active"
    GRACE = "grace"
    ENDED = "ended"
    ERROR = "error"


class SubscriptionBase(BaseModel):
    paypal_subscription_id: str
    status: SubscriptionStatus
    payer_email: str | None = None
    payer_name: str | None = None
    price_cents: int
    currency: str = "EUR"
    next_billing_date: datetime | None = None
    last_payment_failed_at: datetime | None = None
    created: datetime
    activated: datetime | None = None
    ended: datetime | None = None


class SubscriptionDb(SubscriptionBase):
    id: int


class SubscriptionCreateDb(BaseModel):
    paypal_subscription_id: str
    status: SubscriptionStatus
    price_cents: int
    currency: str = "EUR"
    payer_email: str | None = None
    payer_name: str | None = None
    next_billing_date: datetime | None = None
    created: datetime
    activated: datetime | None = None


class SubscriptionUpdateDb(BaseModel):
    status: SubscriptionStatus | None = None
    payer_email: str | None = None
    payer_name: str | None = None
    price_cents: int | None = None
    next_billing_date: datetime | None = None
    last_payment_failed_at: datetime | None = None
    activated: datetime | None = None
    ended: datetime | None = None


class SubscribeResponse(BaseModel):
    subscription_id: str
    approval_url: str
    expected_price_cents: int


class ResizeResponse(BaseModel):
    expected_price_cents: int | None = None
    current_price_cents: int | None = None
    subscription_id: str | None = None
    plan_id: str | None = None
