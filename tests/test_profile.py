from datetime import datetime, timezone

from httpx import AsyncClient

from shard_core.data_model.backend.shard_model import (
    ShardResponse,
    ShardSubscriptionSummary,
)
from shard_core.data_model.backend.subscription_model import SubscriptionStatus
from shard_core.data_model.profile import Profile
from tests import conftest


def test_from_shard_carries_billing_fields():
    now = datetime.now(timezone.utc)
    shard = ShardResponse(
        **conftest.mock_shard.model_dump(),
        telemetry=[],
        telemetry_start=now,
        telemetry_end=now,
        subscription=None,
        billing_enabled=True,
        paypal_client_id="cid",
        paypal_environment="sandbox",
    )
    profile = Profile.from_shard(shard)
    assert profile.billing_enabled is True
    assert profile.paypal_client_id == "cid"
    assert profile.paypal_environment == "sandbox"


def test_from_shard_defaults_billing_disabled():
    # A controller that omits the fields (or has billing off) → safe defaults.
    profile = Profile.from_shard(conftest.mock_shard)
    assert profile.billing_enabled is False
    assert profile.paypal_client_id is None


async def test_profile(requests_mock, app_client: AsyncClient):
    response = await app_client.get("protected/management/profile")
    response.raise_for_status()
    assert Profile.model_validate(response.json()) == Profile.from_shard(
        conftest.mock_shard
    )


async def test_profile_includes_subscription(app_client: AsyncClient):
    subscription = ShardSubscriptionSummary(
        status=SubscriptionStatus.ACTIVE,
        price_cents=499,
        currency="EUR",
        next_billing_date=datetime(2026, 7, 1, tzinfo=timezone.utc),
        payer_email="payer@example.com",
        paypal_manage_url="https://paypal.example/manage/abc",
    )
    with conftest.requests_mock_context(subscription=subscription):
        response = await app_client.get("protected/management/profile")
        response.raise_for_status()
        profile = Profile.model_validate(response.json())
        assert profile.subscription == subscription


async def test_profile_without_subscription_is_none(
    requests_mock, app_client: AsyncClient
):
    response = await app_client.get("protected/management/profile")
    response.raise_for_status()
    profile = Profile.model_validate(response.json())
    assert profile.subscription is None


async def test_profile_includes_volume_size_gb(requests_mock, app_client: AsyncClient):
    response = await app_client.get("protected/management/profile")
    response.raise_for_status()
    profile = Profile.model_validate(response.json())
    assert profile.volume_size_gb == conftest.mock_shard.volume_size_gb
    assert profile.volume_size_gb == 30
