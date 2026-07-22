import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from shard_core.service import backup
from shard_core.service.backup import (
    BackupFailedError,
    _backup_directory,
    _build_backup_command,
    _build_cleartext_backup_command,
    _get_obscured_passphrase,
    _write_marker_blob,
    start_backup,
)


def test_backup_commands_only_use_supported_flags():
    """Guard against reintroducing rclone flags missing from the bundled binary.

    The core image ships rclone 1.60.1 (Debian bookworm), which lacks
    --azureblob-no-check-container (added in 1.61.0). See issue #117.
    """
    argvs = (
        _build_backup_command("sas", "obscured", "container", "dir"),
        _build_cleartext_backup_command("sas", "container", "dir"),
    )
    for argv in argvs:
        assert "--azureblob-no-check-container" not in argv
        assert "--fast-list" in argv


def test_build_backup_command_keeps_whitespace_values_as_single_argv():
    """A SAS URL or path containing whitespace must stay one argv element,
    not be split into several tokens (the bug behind command.split())."""
    sas_with_space = "https://acct.blob.core.windows.net/c?sv=a b&sig=x y"
    argv = _build_backup_command(sas_with_space, "obscured", "container", "my dir")

    assert sas_with_space in argv
    assert "my dir" in argv
    assert argv[0] == "rclone"
    # the crypt destination for a spaced directory stays intact
    assert ":crypt:container/my dir" in argv


@pytest.mark.parametrize(
    "builder,args",
    [
        (_build_backup_command, ("sas", "obscured", "container", "dir")),
        (_build_cleartext_backup_command, ("sas", "container", "dir")),
    ],
)
def test_backup_command_argv_is_flat_string_list(builder, args):
    argv = builder(*args)
    assert all(isinstance(token, str) for token in argv)


def _mock_process(returncode, stdout=b"", stderr=b""):
    process = AsyncMock()
    process.communicate.return_value = (stdout, stderr)
    process.returncode = returncode
    return process


@pytest.mark.asyncio
async def test_backup_directory_returns_stats_on_success():
    stats = {"bytes": 42, "errors": 0}
    stderr = (json.dumps({"stats": stats}) + "\n").encode()
    process = _mock_process(0, stderr=stderr)
    with patch.object(backup.asyncio, "create_subprocess_exec", return_value=process):
        result = await _backup_directory("container", "dir", "obscured", "sas")
    assert result == stats


@pytest.mark.asyncio
async def test_backup_directory_raises_on_nonzero_exit():
    stderr = b"Error: unknown flag: --azureblob-no-check-container\n"
    process = _mock_process(1, stderr=stderr)
    with patch.object(backup.asyncio, "create_subprocess_exec", return_value=process):
        with pytest.raises(BackupFailedError) as exc_info:
            await _backup_directory("container", "dir", "obscured", "sas")
    assert "unknown flag: --azureblob-no-check-container" in str(exc_info.value)


@pytest.mark.asyncio
async def test_get_obscured_passphrase_uses_async_subprocess():
    process = _mock_process(0, stdout=b"OBSCURED\n")
    create = AsyncMock(return_value=process)
    with (
        patch.object(backup.asyncio, "create_subprocess_exec", create),
        patch.object(backup.database, "get_value", AsyncMock(return_value="secret")),
    ):
        result = await _get_obscured_passphrase()

    assert result == "OBSCURED"
    create.assert_awaited_once()
    assert create.await_args.args == ("rclone", "obscure", "secret")


@pytest.mark.asyncio
async def test_get_obscured_passphrase_raises_on_nonzero_exit():
    process = _mock_process(1, stderr=b"boom\n")
    with (
        patch.object(
            backup.asyncio, "create_subprocess_exec", AsyncMock(return_value=process)
        ),
        patch.object(backup.database, "get_value", AsyncMock(return_value="secret")),
    ):
        with pytest.raises(BackupFailedError) as exc_info:
            await _get_obscured_passphrase()
    assert "boom" in str(exc_info.value)


@pytest.mark.asyncio
async def test_write_marker_blob_offloads_upload_to_thread():
    """The blocking Azure upload must run in a worker thread, never directly on
    the event loop."""
    blob_client = MagicMock()
    to_thread = AsyncMock()
    with (
        patch.object(backup.BlobClient, "from_blob_url", return_value=blob_client),
        patch.object(backup.asyncio, "to_thread", to_thread),
    ):
        await _write_marker_blob(
            "container", "https://acct.blob.core.windows.net/c?sv=x&sig=y"
        )

    # upload happened via to_thread, not a direct (loop-blocking) call
    blob_client.upload_blob.assert_not_called()
    to_thread.assert_awaited_once()
    assert to_thread.await_args.args[0] == blob_client.upload_blob


@pytest.mark.asyncio
async def test_write_marker_blob_swallows_errors():
    with patch.object(
        backup.BlobClient, "from_blob_url", side_effect=RuntimeError("nope")
    ):
        # must not raise - the marker is best-effort
        await _write_marker_blob("container", "https://acct/c?sig=y")


@pytest.mark.asyncio
async def test_start_backup_keeps_strong_reference_to_task():
    """The backup task must be held by the module-level set so it cannot be
    garbage-collected mid-run."""
    release = asyncio.Event()
    started = asyncio.Event()

    async def fake_backup(*_args, **_kwargs):
        started.set()
        await release.wait()

    sas = SimpleNamespace(container_name="c", sas_url="s")
    with (
        patch.object(backup, "get_backup_sas_url", AsyncMock(return_value=sas)),
        patch.object(backup, "backup_directories", fake_backup),
        patch.object(backup.signals, "on_backup_update"),
    ):
        assert backup.background_tasks == set()
        await start_backup()
        await asyncio.wait_for(started.wait(), timeout=5)

        assert len(backup.background_tasks) == 1

        release.set()
        for _ in range(100):
            await asyncio.sleep(0)
            if not backup.background_tasks:
                break
        assert backup.background_tasks == set()
