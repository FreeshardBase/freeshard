import json
from unittest.mock import AsyncMock, MagicMock, patch

from requests import HTTPError

from shard_core.service import disk_full_notification as dfn
from shard_core.service.disk import DiskUsage
from tests.conftest import settings_override


def _usage(used_percent: float, total_gb: float = 100.0) -> DiskUsage:
    free_gb = total_gb * (1 - used_percent / 100)
    return DiskUsage(total_gb=total_gb, free_gb=free_gb, disk_space_low=False)


def _enabled(threshold_percent: float = 90):
    return settings_override(
        {
            "event_notifications": {
                "disk_full": {"enabled": True, "threshold_percent": threshold_percent}
            }
        }
    )


def _patch_relay():
    """Patch the controller relay call with a 201-style success response."""
    mock_call = AsyncMock()
    mock_call.return_value = MagicMock()  # requests.Response with sync raise_for_status
    return patch(
        "shard_core.service.disk_full_notification.call_freeshard_controller",
        mock_call,
    )


async def test_sends_email_when_over_threshold(app_client):
    with _enabled(), _patch_relay() as mock_call:
        await dfn.check_disk_full(_usage(95))

    assert mock_call.await_count == 1
    call = mock_call.await_args
    assert call.args[0] == "api/email_relay"
    assert call.kwargs["method"] == "POST"
    payload = json.loads(call.kwargs["body"].decode())
    assert isinstance(payload["body"], list)
    assert "95%" in " ".join(payload["body"])


async def test_does_not_send_below_threshold(app_client):
    with _enabled(), _patch_relay() as mock_call:
        await dfn.check_disk_full(_usage(50))

    assert not mock_call.called


async def test_dedupe_only_sends_once(app_client):
    with _enabled(), _patch_relay() as mock_call:
        await dfn.check_disk_full(_usage(95))
        await dfn.check_disk_full(_usage(96))
        await dfn.check_disk_full(_usage(97))

    assert mock_call.await_count == 1


async def test_resets_after_dropping_below_threshold(app_client):
    with _enabled(), _patch_relay() as mock_call:
        await dfn.check_disk_full(_usage(95))  # sent
        await dfn.check_disk_full(_usage(50))  # re-armed
        await dfn.check_disk_full(_usage(95))  # sent again

    assert mock_call.await_count == 2


async def test_opt_out_when_disabled(app_client):
    override = {"event_notifications": {"disk_full": {"enabled": False}}}
    with settings_override(override), _patch_relay() as mock_call:
        await dfn.check_disk_full(_usage(99))

    assert not mock_call.called


async def test_send_failure_does_not_set_flag_and_retries(app_client):
    with _enabled(), _patch_relay() as mock_call:
        mock_call.side_effect = RuntimeError("controller offline")
        await dfn.check_disk_full(_usage(95))
        assert await dfn._was_notified() is False

        mock_call.side_effect = None
        await dfn.check_disk_full(_usage(95))

    assert mock_call.await_count == 2
    assert await dfn._was_notified() is True


async def test_error_status_does_not_set_flag(app_client):
    with _enabled(), _patch_relay() as mock_call:
        mock_call.return_value.raise_for_status.side_effect = HTTPError("429")
        await dfn.check_disk_full(_usage(95))
        assert await dfn._was_notified() is False


async def test_ignores_unmeasured_disk(app_client):
    with _enabled(), _patch_relay() as mock_call:
        await dfn.check_disk_full(
            DiskUsage(total_gb=0, free_gb=0, disk_space_low=False)
        )

    assert not mock_call.called


async def test_email_is_english(app_client):
    with _enabled(), _patch_relay() as mock_call:
        await dfn.check_disk_full(_usage(95))

    payload = json.loads(mock_call.await_args.kwargs["body"].decode())
    assert payload["subject"] == dfn._TEMPLATES["en"]["subject"]
    assert payload["body"][0] == "Hello,"
