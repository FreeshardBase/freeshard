import json
from unittest.mock import AsyncMock, patch

import pytest

from shard_core.service import backup
from shard_core.service.backup import (
    COMMAND_TEMPLATE,
    CLEARTEXT_COMMAND_TEMPLATE,
    BackupFailedError,
    _backup_directory,
)


def test_command_templates_only_use_supported_flags():
    """Guard against reintroducing rclone flags missing from the bundled binary.

    The core image ships rclone 1.60.1 (Debian bookworm), which lacks
    --azureblob-no-check-container (added in 1.61.0). See issue #117.
    """
    for template in (COMMAND_TEMPLATE, CLEARTEXT_COMMAND_TEMPLATE):
        assert "--azureblob-no-check-container" not in template
        assert "--fast-list" in template


def _mock_process(returncode, stderr):
    process = AsyncMock()
    process.communicate.return_value = (b"", stderr)
    process.returncode = returncode
    return process


@pytest.mark.asyncio
async def test_backup_directory_returns_stats_on_success():
    stats = {"bytes": 42, "errors": 0}
    stderr = (json.dumps({"stats": stats}) + "\n").encode()
    process = _mock_process(0, stderr)
    with patch.object(backup.asyncio, "create_subprocess_exec", return_value=process):
        result = await _backup_directory("container", "dir", "obscured", "sas")
    assert result == stats


@pytest.mark.asyncio
async def test_backup_directory_raises_on_nonzero_exit():
    stderr = b"Error: unknown flag: --azureblob-no-check-container\n"
    process = _mock_process(1, stderr)
    with patch.object(backup.asyncio, "create_subprocess_exec", return_value=process):
        with pytest.raises(BackupFailedError) as exc_info:
            await _backup_directory("container", "dir", "obscured", "sas")
    assert "unknown flag: --azureblob-no-check-container" in str(exc_info.value)
