import json
from unittest.mock import AsyncMock, MagicMock, patch

from requests import HTTPError

from shard_core.service import disk
from shard_core.service import disk_full_notification as dfn
from shard_core.service.disk import DiskUsage
from tests.conftest import settings_override


def _usage_at(used_percent: float, total_gb: float = 100.0) -> DiskUsage:
    free_gb = total_gb * (1 - used_percent / 100)
    return DiskUsage(total_gb=total_gb, free_gb=free_gb, disk_space_low=False)


def _enabled_config(threshold_percent: float = 90):
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
    with _enabled_config(), _patch_relay() as mock_call:
        await dfn.check_disk_full(_usage_at(95))

    assert mock_call.await_count == 1
    call = mock_call.await_args
    assert call.args[0] == "api/email_relay"
    assert call.kwargs["method"] == "POST"
    payload = json.loads(call.kwargs["body"].decode())
    assert isinstance(payload["body"], list)
    assert "95%" in " ".join(payload["body"])


async def test_triggers_at_exact_threshold(app_client):
    with _enabled_config(90), _patch_relay() as mock_call:
        await dfn.check_disk_full(_usage_at(90))

    assert mock_call.await_count == 1


async def test_does_not_trigger_just_below_threshold(app_client):
    with _enabled_config(90), _patch_relay() as mock_call:
        await dfn.check_disk_full(_usage_at(89))

    assert not mock_call.called


async def test_does_not_send_below_threshold(app_client):
    with _enabled_config(), _patch_relay() as mock_call:
        await dfn.check_disk_full(_usage_at(50))

    assert not mock_call.called


async def test_dedupe_only_sends_once(app_client):
    with _enabled_config(), _patch_relay() as mock_call:
        await dfn.check_disk_full(_usage_at(95))
        await dfn.check_disk_full(_usage_at(96))
        await dfn.check_disk_full(_usage_at(97))

    assert mock_call.await_count == 1


async def test_resets_after_dropping_below_threshold(app_client):
    with _enabled_config(), _patch_relay() as mock_call:
        await dfn.check_disk_full(_usage_at(95))  # sent
        assert await dfn._was_notified() is True
        await dfn.check_disk_full(_usage_at(50))  # re-armed
        assert await dfn._was_notified() is False
        await dfn.check_disk_full(_usage_at(95))  # sent again

    assert mock_call.await_count == 2


async def test_opt_out_when_disabled(app_client):
    override = {"event_notifications": {"disk_full": {"enabled": False}}}
    with settings_override(override), _patch_relay() as mock_call:
        await dfn.check_disk_full(_usage_at(99))

    assert not mock_call.called


async def test_send_failure_does_not_set_flag_and_retries(app_client):
    with _enabled_config(), _patch_relay() as mock_call:
        mock_call.side_effect = RuntimeError("controller offline")
        await dfn.check_disk_full(_usage_at(95))
        assert await dfn._was_notified() is False

        mock_call.side_effect = None
        await dfn.check_disk_full(_usage_at(95))

    assert mock_call.await_count == 2
    assert await dfn._was_notified() is True


async def test_error_status_does_not_set_flag(app_client):
    with _enabled_config(), _patch_relay() as mock_call:
        mock_call.return_value.raise_for_status.side_effect = HTTPError("429")
        await dfn.check_disk_full(_usage_at(95))
        assert await dfn._was_notified() is False


async def test_ignores_unmeasured_disk(app_client):
    with _enabled_config(), _patch_relay() as mock_call:
        await dfn.check_disk_full(
            DiskUsage(total_gb=0, free_gb=0, disk_space_low=False)
        )

    assert not mock_call.called


async def test_run_check_uses_current_disk_snapshot(app_client, mocker):
    """run_check is the background-task entry point; it must read the live snapshot."""
    mocker.patch.object(disk, "current_disk_usage", _usage_at(95))
    with _enabled_config(), _patch_relay() as mock_call:
        await dfn.run_check()

    assert mock_call.await_count == 1


async def test_email_is_english(app_client):
    with _enabled_config(), _patch_relay() as mock_call:
        await dfn.check_disk_full(_usage_at(95))

    payload = json.loads(mock_call.await_args.kwargs["body"].decode())
    assert payload["subject"] == "Your Freeshard is running low on disk space"
    assert payload["body"][0] == "Hello,"
    assert any("will not receive another" in line for line in payload["body"])


def test_both_templates_are_well_formed():
    for lang in ("en", "de"):
        template = dfn._TEMPLATES[lang]
        assert template["subject"]
        rendered = [line.format(used_percent=90) for line in template["body"]]
        assert any("90%" in line for line in rendered)
