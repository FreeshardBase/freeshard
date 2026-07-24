"""Compose commands for an app must never resolve to the core stack.

The app dirs live under the core dir, so a cwd-based compose invocation with a
missing app compose file walks up to /core/docker-compose.yml and operates on
project "core" — stopping shard_core itself (issue #160).
"""

import asyncio
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
    SubprocessError,
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
    """start_app's @throttle(5) is per-app but persists across tests — a start
    of the same app in an earlier test would silently drop our call."""
    wrapper = app_tools.start_app
    cell = wrapper.__closure__[wrapper.__code__.co_freevars.index("last_call")]
    cell.cell_contents.clear()


async def _insert_app(name: str, status: Status):
    async with db_conn() as conn:
        await db_installed_apps.insert(
            conn, InstalledApp(name=name, status=status).model_dump()
        )


@pytest.mark.parametrize(
    "operation, status",
    [
        (app_tools.docker_create_app_containers, Status.STOPPED),
        (app_tools.start_app, Status.STOPPED),
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


async def _status(name: str) -> str | None:
    async with db_conn() as conn:
        app = await db_installed_apps.get_by_name(conn, name)
    return app["status"] if app else None


def _issued_commands(subprocess_mock) -> list[tuple]:
    return [call.args for call in subprocess_mock.await_args_list]


@pytest.mark.parametrize(
    "ps_ids, inspect_states, expected",
    [
        ("cid1\ncid2\n", "running\nrunning\n", "running"),
        ("cid1\ncid2\n", "running\npaused\n", "paused"),
        ("cid1\ncid2\n", "paused\nexited\n", "paused"),
        ("cid1\ncid2\n", "running\nexited\n", "exited"),
        ("cid1\n", "created\n", "exited"),
        ("", None, "missing"),
    ],
)
async def test_get_app_container_state_categorizes_real_state(
    tmp_path, subprocess_mock, ps_ids, inspect_states, expected
):
    _app_dir(tmp_path, "app1")
    if inspect_states is None:
        subprocess_mock.side_effect = [ps_ids]
    else:
        subprocess_mock.side_effect = [ps_ids, inspect_states]

    with settings_override({"path_root": str(tmp_path)}):
        state = await app_tools.get_app_container_state("app1")

    assert state == expected


async def test_get_app_container_state_missing_when_ps_fails(tmp_path, subprocess_mock):
    _app_dir(tmp_path, "app1")
    subprocess_mock.side_effect = SubprocessError("no such project")

    with settings_override({"path_root": str(tmp_path)}):
        state = await app_tools.get_app_container_state("app1")

    assert state == "missing"


async def test_start_app_revives_exited_app_even_when_db_says_paused(
    db, tmp_path, subprocess_mock
):
    """The #185 bug: db says PAUSED but the container exited (crash / OOM /
    core-upgrade converge). The old wake ran `unpause` and crashed; revive must
    `up -d` instead."""
    _app_dir(tmp_path, "exited_app")
    await _insert_app("exited_app", Status.PAUSED)

    with (
        settings_override({"path_root": str(tmp_path)}),
        patch.object(
            app_tools, "get_app_container_state", new=AsyncMock(return_value="exited")
        ),
    ):
        await app_tools.start_app("exited_app")

    commands = _issued_commands(subprocess_mock)
    assert any(c[-2:] == ("up", "-d") for c in commands)
    assert not any("unpause" in c for c in commands)
    assert await _status("exited_app") == Status.RUNNING


async def test_start_app_unpauses_a_genuinely_paused_app(db, tmp_path, subprocess_mock):
    _app_dir(tmp_path, "paused_app")
    await _insert_app("paused_app", Status.PAUSED)

    with (
        settings_override({"path_root": str(tmp_path)}),
        patch.object(
            app_tools, "get_app_container_state", new=AsyncMock(return_value="paused")
        ),
    ):
        await app_tools.start_app("paused_app")

    commands = _issued_commands(subprocess_mock)
    assert any(c[-1] == "unpause" for c in commands)
    assert not any(c[-2:] == ("up", "-d") for c in commands)
    assert await _status("paused_app") == Status.RUNNING


async def test_start_app_running_container_is_a_noop_but_reconciles_status(
    db, tmp_path, subprocess_mock
):
    _app_dir(tmp_path, "running_app")
    await _insert_app("running_app", Status.PAUSED)

    with (
        settings_override({"path_root": str(tmp_path)}),
        patch.object(
            app_tools, "get_app_container_state", new=AsyncMock(return_value="running")
        ),
    ):
        await app_tools.start_app("running_app")

    subprocess_mock.assert_not_called()
    assert await _status("running_app") == Status.RUNNING


async def test_start_app_starts_a_missing_stack(db, tmp_path, subprocess_mock):
    _app_dir(tmp_path, "gone_app")
    await _insert_app("gone_app", Status.DOWN)

    with (
        settings_override({"path_root": str(tmp_path)}),
        patch.object(
            app_tools, "get_app_container_state", new=AsyncMock(return_value="missing")
        ),
    ):
        await app_tools.start_app("gone_app")

    commands = _issued_commands(subprocess_mock)
    assert any(c[-2:] == ("up", "-d") for c in commands)
    assert await _status("gone_app") == Status.RUNNING


@pytest.mark.parametrize(
    "status", [Status.ERROR, Status.UNINSTALLING, Status.INSTALLING]
)
async def test_start_app_skips_non_revivable_status(
    db, tmp_path, subprocess_mock, status
):
    """A revive must never start an app that is being uninstalled/reinstalled or
    is in ERROR — otherwise the always-on control tick recreates its containers
    mid-teardown."""
    _app_dir(tmp_path, "term_app")
    await _insert_app("term_app", status)

    with settings_override({"path_root": str(tmp_path)}):
        await app_tools.start_app("term_app")

    subprocess_mock.assert_not_called()
    assert await _status("term_app") == status


async def test_start_app_falls_back_to_up_when_unpause_fails(
    db, tmp_path, subprocess_mock
):
    """A partially-paused stack (some containers already exited) can't be revived
    by unpause — start_app must fall back to `up -d` instead of crashing."""
    _app_dir(tmp_path, "mixed_app")
    await _insert_app("mixed_app", Status.PAUSED)
    subprocess_mock.side_effect = [
        SubprocessError("Container mixed_app is not paused"),  # unpause
        "",  # up -d fallback
    ]

    with (
        settings_override({"path_root": str(tmp_path)}),
        patch.object(
            app_tools, "get_app_container_state", new=AsyncMock(return_value="paused")
        ),
    ):
        await app_tools.start_app("mixed_app")

    commands = _issued_commands(subprocess_mock)
    assert commands[0][-1] == "unpause"
    assert commands[-1][-2:] == ("up", "-d")
    assert await _status("mixed_app") == Status.RUNNING


@pytest.mark.parametrize(
    "error_text", ["network portal not found", "Conflict already in use"]
)
async def test_start_app_recovers_stale_containers(
    db, tmp_path, subprocess_mock, error_text
):
    _app_dir(tmp_path, "stale_app")
    await _insert_app("stale_app", Status.DOWN)
    subprocess_mock.side_effect = [
        SubprocessError(error_text),  # first up -d
        "",  # down
        "",  # up -d retry
    ]

    with (
        settings_override({"path_root": str(tmp_path)}),
        patch.object(
            app_tools, "get_app_container_state", new=AsyncMock(return_value="exited")
        ),
    ):
        await app_tools.start_app("stale_app")

    commands = _issued_commands(subprocess_mock)
    assert commands[0][-2:] == ("up", "-d")
    assert commands[1][-1] == "down"
    assert commands[2][-2:] == ("up", "-d")
    assert await _status("stale_app") == Status.RUNNING


async def test_start_app_is_serialized_by_the_per_app_op_lock(
    db, tmp_path, subprocess_mock
):
    """start_app and an uninstall teardown must not interleave: both hold the
    per-app op lock, so a revive can't recreate a container after the uninstall
    worker removed it (issue #185 follow-up). While the lock is held, start_app
    blocks and issues no compose command."""
    _app_dir(tmp_path, "locked_app")
    await _insert_app("locked_app", Status.RUNNING)

    lock = app_tools.app_op_lock("locked_app")
    assert app_tools.app_op_lock("locked_app") is lock  # one lock per app name

    with (
        settings_override({"path_root": str(tmp_path)}),
        patch.object(
            app_tools, "get_app_container_state", new=AsyncMock(return_value="missing")
        ),
    ):
        await lock.acquire()
        try:
            task = asyncio.create_task(app_tools.start_app("locked_app"))
            await asyncio.sleep(0.05)
            assert not task.done()  # blocked on the lock, no compose up yet
            subprocess_mock.assert_not_called()
        finally:
            lock.release()
        await asyncio.wait_for(task, timeout=1)
