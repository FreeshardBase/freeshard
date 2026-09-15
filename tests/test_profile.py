from datetime import datetime, timezone

import pytest
from httpx import AsyncClient
from pydantic import ValidationError

from shard_core.data_model.backend.shard_model import (
    Cloud,
    ShardResponse,
    ShardSubscriptionSummary,
)
from shard_core.data_model.backend.subscription_model import SubscriptionStatus
from shard_core.data_model.profile import Profile
from tests import conftest


def _shard_self_payload(cloud: str) -> dict:
    """The body `refresh_profile` validates, with the cloud as the wire sends it."""
    now = datetime.now(timezone.utc)
    return {
        **conftest.mock_shard.model_dump(mode="json"),
        "cloud": cloud,
        "telemetry": [],
        "telemetry_start": now.isoformat(),
        "telemetry_end": now.isoformat(),
    }


def test_a_shard_on_ionos_can_read_its_own_profile():
    """The controller may answer `GET /shards/self` with cloud=ionos. Before the
    vendored enum learned that value, model_validate raised and both
    refresh_profile and refresh_shared_secret died with it."""
    shard = ShardResponse.model_validate(_shard_self_payload("ionos"))

    assert shard.cloud is Cloud.IONOS
    assert Profile.from_shard(shard).vm_id == conftest.mock_shard.machine_id


def test_an_unknown_cloud_is_still_rejected():
    """Proves the test above has teeth: the field really is validated against
    the enum, so a value missing from it fails rather than passing through."""
    with pytest.raises(ValidationError):
        ShardResponse.model_validate(_shard_self_payload("hetzner"))


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
