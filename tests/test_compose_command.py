from unittest.mock import patch, MagicMock
import subprocess as _sp

from shard_core.util.subprocess import _detect_compose_command, compose_command


def _clear_cache():
    _detect_compose_command.cache_clear()


def test_compose_command_prefers_plugin():
    _clear_cache()
    mock_result = MagicMock()
    mock_result.returncode = 0
    with patch(
        "shard_core.util.subprocess._sp.run", return_value=mock_result
    ) as mock_run:
        result = compose_command()
    mock_run.assert_called_once_with(
        ["docker", "compose", "version"],
        capture_output=True,
        timeout=5,
    )
    assert result == ("docker", "compose")
    _clear_cache()


def test_compose_command_falls_back_on_nonzero():
    _clear_cache()
    mock_result = MagicMock()
    mock_result.returncode = 1
    with patch("shard_core.util.subprocess._sp.run", return_value=mock_result):
        result = compose_command()
    assert result == ("docker-compose",)
    _clear_cache()


def test_compose_command_falls_back_on_file_not_found():
    _clear_cache()
    with patch("shard_core.util.subprocess._sp.run", side_effect=FileNotFoundError):
        result = compose_command()
    assert result == ("docker-compose",)
    _clear_cache()


def test_compose_command_falls_back_on_timeout():
    _clear_cache()
    with patch(
        "shard_core.util.subprocess._sp.run",
        side_effect=_sp.TimeoutExpired(cmd="docker", timeout=5),
    ):
        result = compose_command()
    assert result == ("docker-compose",)
    _clear_cache()


def test_compose_command_cached():
    _clear_cache()
    mock_result = MagicMock()
    mock_result.returncode = 0
    with patch(
        "shard_core.util.subprocess._sp.run", return_value=mock_result
    ) as mock_run:
        compose_command()
        compose_command()
    assert mock_run.call_count == 1
    _clear_cache()
