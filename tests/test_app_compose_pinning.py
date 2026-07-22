"""Compose commands for an app must never resolve to the core stack.

The app dirs live under the core dir, so a cwd-based compose invocation with a
missing app compose file walks up to /core/docker-compose.yml and operates on
project "core" — stopping shard_core itself (issue #160).
"""

from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from shard_core.data_model.app_meta import InstalledApp, Status
from shard_core.database.connection import db_conn
from shard_core.database import installed_apps as db_installed_apps
from shard_core.service import app_tools
from shard_core.util.subprocess import (
    ComposeFileNotFound,
    ComposeProjectNotAllowed,
    app_compose_command,
    normalize_project_name,
)
from tests.conftest import settings_override

COMPOSE_FILE_CONTENT = "services:\n  a:\n    image: nginx:alpine\n"


def _app_dir(root: Path, name: str, with_compose_file: bool = True) -> Path:
    app_dir = root / "core" / "installed_apps" / name
    app_dir.mkdir(parents=True)
    if with_compose_file:
        (app_dir / "docker-compose.yml").write_text(COMPOSE_FILE_CONTENT)
    return app_dir


def test_app_compose_command_pins_file_and_project(tmp_path):
    app_dir = _app_dir(tmp_path, "filebrowser")

    command = app_compose_command(app_dir)

    assert command[-6:] == (
        "-f",
        str(app_dir / "docker-compose.yml"),
        "-p",
        "filebrowser",
        "--project-directory",
        str(app_dir),
    )


def test_app_compose_command_without_compose_file_raises(tmp_path):
    app_dir = _app_dir(tmp_path, "filebrowser", with_compose_file=False)

    with pytest.raises(ComposeFileNotFound):
        app_compose_command(app_dir)


def test_app_compose_command_rejects_core_project(tmp_path):
    core_dir = tmp_path / "core"
    core_dir.mkdir()
    (core_dir / "docker-compose.yml").write_text(COMPOSE_FILE_CONTENT)

    with pytest.raises(ComposeProjectNotAllowed):
        app_compose_command(core_dir)


def test_app_compose_command_rejects_dir_without_valid_project_name(tmp_path):
    app_dir = _app_dir(tmp_path, "...")

    with pytest.raises(ComposeProjectNotAllowed):
        app_compose_command(app_dir)


@pytest.mark.parametrize(
    "dir_name, expected",
    [
        ("filebrowser", "filebrowser"),
        ("paperless-ngx", "paperless-ngx"),
        ("always_on", "always_on"),
        # verified against `docker compose config` (v5.0.2): lowercase, drop
        # everything outside [a-z0-9_-], strip leading _ and -
        ("My_App.v2-x", "my_appv2-x"),
        ("_-Foo", "foo"),
    ],
)
def test_normalize_project_name_matches_compose(dir_name, expected):
    assert normalize_project_name(dir_name) == expected


@pytest.fixture
def subprocess_mock():
    with patch.object(app_tools, "subprocess", new=AsyncMock()) as mock:
        yield mock


@pytest.fixture(autouse=True)
def reset_start_throttle():
    """docker_start_app's @throttle(5) is per-app but persists across tests — a
    start of the same app in an earlier test would silently drop our call."""
    app_tools.docker_start_app.reset()


async def _insert_app(name: str, status: Status):
    async with db_conn() as conn:
        await db_installed_apps.insert(
            conn, InstalledApp(name=name, status=status).model_dump()
        )


@pytest.mark.parametrize(
    "operation, status",
    [
        (app_tools.docker_create_app_containers, Status.STOPPED),
        (app_tools.docker_start_app, Status.STOPPED),
        (app_tools.docker_pause_app, Status.RUNNING),
        (app_tools.docker_unpause_app, Status.PAUSED),
        (app_tools.docker_stop_app, Status.RUNNING),
        (app_tools.docker_shutdown_app, Status.STOPPED),
    ],
)
async def test_app_operation_without_compose_file_never_runs_compose(
    db, tmp_path, subprocess_mock, operation, status
):
    _app_dir(tmp_path, "brokenapp", with_compose_file=False)
    await _insert_app("brokenapp", status)

    with settings_override({"path_root": str(tmp_path)}):
        with pytest.raises(ComposeFileNotFound):
            await operation("brokenapp")

    subprocess_mock.assert_not_called()


async def test_app_operation_with_compose_file_pins_the_app_project(
    db, tmp_path, subprocess_mock
):
    app_dir = _app_dir(tmp_path, "brokenapp")
    await _insert_app("brokenapp", Status.RUNNING)

    with settings_override({"path_root": str(tmp_path)}):
        await app_tools.docker_stop_app("brokenapp")

    command = subprocess_mock.await_args.args
    assert command[-1] == "stop"
    assert "-p" in command and command[command.index("-p") + 1] == "brokenapp"
    assert "-f" in command and command[command.index("-f") + 1] == str(
        app_dir / "docker-compose.yml"
    )


def _started_apps(subprocess_mock) -> list[str]:
    return [
        c.args[c.args.index("-p") + 1]
        for c in subprocess_mock.call_args_list
        if c.args[-2:] == ("up", "-d")
    ]


async def test_docker_start_app_starts_each_app_despite_throttle(
    db, tmp_path, subprocess_mock
):
    _app_dir(tmp_path, "appa")
    _app_dir(tmp_path, "appb")
    await _insert_app("appa", Status.STOPPED)
    await _insert_app("appb", Status.STOPPED)

    with settings_override({"path_root": str(tmp_path)}):
        await app_tools.docker_start_app("appa")
        await app_tools.docker_start_app("appb")

    assert _started_apps(subprocess_mock) == ["appa", "appb"]


async def test_docker_start_app_throttles_repeated_start_of_same_app(
    db, tmp_path, subprocess_mock
):
    _app_dir(tmp_path, "appa")
    await _insert_app("appa", Status.STOPPED)

    with settings_override({"path_root": str(tmp_path)}):
        await app_tools.docker_start_app("appa")
        # force back to a startable status so only the throttle, not status
        # gating, can drop the second start
        async with db_conn() as conn:
            await db_installed_apps.update_status(conn, "appa", Status.STOPPED)
        await app_tools.docker_start_app("appa")

    assert _started_apps(subprocess_mock) == ["appa"]
