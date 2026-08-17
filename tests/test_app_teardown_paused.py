"""Tearing down a frozen stack must not depend on the stored status.

A paused container can neither be stopped nor removed, and the status a teardown
sees is often not PAUSED: REINSTALLING during a reinstall, ERROR on a shard the
reinstall already broke, or a stale RUNNING after an out-of-band pause. The
unpause is therefore decided from the real container state (issue #199).
"""

from contextlib import contextmanager
from pathlib import Path
from unittest.mock import AsyncMock, Mock, patch

import pytest

from shard_core.data_model.app_meta import InstalledApp, Status
from shard_core.database.connection import db_conn
from shard_core.database import installed_apps as db_installed_apps
from shard_core.service import app_installation, app_tools
from shard_core.service.app_installation import util as installation_util
from shard_core.service.app_installation import worker
from shard_core.util.subprocess import SubprocessError
from tests.conftest import settings_override

COMPOSE_FILE_CONTENT = "services:\n  a:\n    image: nginx:alpine\n"


def _app_dir(root: Path, name: str) -> Path:
    app_dir = root / "core" / "installed_apps" / name
    app_dir.mkdir(parents=True)
    (app_dir / "docker-compose.yml").write_text(COMPOSE_FILE_CONTENT)
    return app_dir


async def _insert_app(name: str, status: Status):
    async with db_conn() as conn:
        await db_installed_apps.insert(
            conn, InstalledApp(name=name, status=status).model_dump()
        )


async def _status(name: str) -> str | None:
    async with db_conn() as conn:
        app = await db_installed_apps.get_by_name(conn, name)
    return app["status"] if app else None


@pytest.fixture
def subprocess_mock():
    with patch.object(app_tools, "subprocess", new=AsyncMock()) as mock:
        yield mock


def _issued_commands(subprocess_mock) -> list[tuple]:
    return [call.args for call in subprocess_mock.await_args_list]


def _verbs(subprocess_mock) -> list[str]:
    return [c[-1] for c in _issued_commands(subprocess_mock)]


def _container_state(state: str):
    return patch.object(
        app_tools, "get_app_container_state", new=AsyncMock(return_value=state)
    )


@pytest.mark.parametrize(
    "status", [Status.REINSTALLING, Status.ERROR, Status.RUNNING, Status.STOPPED]
)
async def test_shutdown_unfreezes_a_frozen_stack_whatever_the_status_says(
    db, tmp_path, subprocess_mock, status
):
    _app_dir(tmp_path, "frozen_app")
    await _insert_app("frozen_app", status)

    with settings_override({"path_root": str(tmp_path)}), _container_state("paused"):
        await app_tools.docker_shutdown_app("frozen_app", force=True)

    assert _verbs(subprocess_mock) == ["unpause", "down"]


async def test_shutdown_does_not_unpause_an_unfrozen_stack(
    db, tmp_path, subprocess_mock
):
    _app_dir(tmp_path, "stopped_app")
    await _insert_app("stopped_app", Status.STOPPED)

    with settings_override({"path_root": str(tmp_path)}), _container_state("exited"):
        await app_tools.docker_shutdown_app("stopped_app")

    assert _verbs(subprocess_mock) == ["down"]


@pytest.mark.parametrize("status", [Status.RUNNING, Status.UNINSTALLING])
async def test_stop_unfreezes_a_frozen_stack_whatever_the_status_says(
    db, tmp_path, subprocess_mock, status
):
    _app_dir(tmp_path, "frozen_app")
    await _insert_app("frozen_app", status)

    with settings_override({"path_root": str(tmp_path)}), _container_state("paused"):
        await app_tools.docker_stop_app("frozen_app", set_status=False)

    assert _verbs(subprocess_mock) == ["unpause", "stop"]


async def test_stop_does_not_unpause_when_the_stack_is_not_frozen(
    db, tmp_path, subprocess_mock
):
    """The db can say PAUSED while the containers exited out-of-band — unpausing
    that stack fails, so the real state has to decide here too."""
    _app_dir(tmp_path, "exited_app")
    await _insert_app("exited_app", Status.PAUSED)

    with settings_override({"path_root": str(tmp_path)}), _container_state("exited"):
        await app_tools.docker_stop_app("exited_app")

    assert _verbs(subprocess_mock) == ["stop"]
    assert await _status("exited_app") == Status.STOPPED


async def test_teardown_continues_when_unpause_fails(db, tmp_path, subprocess_mock):
    """A partially-paused stack rejects unpause. Aborting the teardown there is
    exactly the failure this fix removes, so `down` must still be attempted."""
    _app_dir(tmp_path, "mixed_app")
    await _insert_app("mixed_app", Status.REINSTALLING)
    subprocess_mock.side_effect = [
        SubprocessError("Container mixed_app is not paused"),  # unpause
        "",  # down
    ]

    with settings_override({"path_root": str(tmp_path)}), _container_state("paused"):
        await app_tools.docker_shutdown_app("mixed_app", force=True)

    assert _verbs(subprocess_mock) == ["unpause", "down"]


async def test_shutdown_all_apps_removes_a_frozen_stack_with_a_stale_status(
    db, tmp_path, subprocess_mock
):
    """Core restart: docker_shutdown_all_apps(force=True) must remove a stack
    whose containers are paused but whose row says something else (issue #200)."""
    _app_dir(tmp_path, "frozen_app")
    await _insert_app("frozen_app", Status.ERROR)

    with settings_override({"path_root": str(tmp_path)}), _container_state("paused"):
        await app_tools.docker_shutdown_all_apps(force=True)

    assert _verbs(subprocess_mock) == ["unpause", "down"]
    assert await _status("frozen_app") == Status.DOWN


@contextmanager
def _reinstall_mocks():
    """Stub out everything the reinstall does besides driving docker: the store
    lookup and download, the zip extraction, and the identity-dependent
    rendering."""

    async def fake_download(name: str) -> Path:
        app_dir = app_tools.get_installed_apps_path() / name
        app_dir.mkdir(parents=True, exist_ok=True)
        (app_dir / "docker-compose.yml").write_text(COMPOSE_FILE_CONTENT)
        zip_file = app_dir / f"{name}.zip"
        zip_file.write_bytes(b"")
        return zip_file

    with (
        patch.object(worker, "_download_app_zip", new=fake_download),
        patch.object(worker, "extract_app_zip", new=Mock()),
        patch.object(worker, "render_docker_compose_template", new=AsyncMock()),
        patch.object(worker, "write_traefik_dyn_config", new=AsyncMock()),
        patch.object(
            installation_util, "app_exists_in_store", new=AsyncMock(return_value=True)
        ),
    ):
        yield


@pytest.mark.parametrize("initial_status", [Status.PAUSED, Status.ERROR])
async def test_reinstall_removes_frozen_containers_before_creating_new_ones(
    db, tmp_path, subprocess_mock, initial_status
):
    """The #199 regression: the old stack outlived the reinstall, so
    `compose up --no-start` ran against paused containers and errored out. ERROR
    is the state shards already broken by the bug sit in — reinstalling must
    repair them rather than fail again."""
    _app_dir(tmp_path, "frozen_app")
    await _insert_app("frozen_app", initial_status)

    with (
        settings_override({"path_root": str(tmp_path)}),
        _container_state("paused"),
        _reinstall_mocks(),
    ):
        await app_installation.reinstall_app("frozen_app")
        await worker._reinstall_app("frozen_app")

    commands = _issued_commands(subprocess_mock)
    assert _verbs(subprocess_mock)[:2] == ["unpause", "down"]
    assert commands[-1][-2:] == ("up", "--no-start")
    assert len(commands) == 3
    assert await _status("frozen_app") == Status.STOPPED


@pytest.mark.parametrize(
    "initial_status, container_state",
    [(Status.RUNNING, "running"), (Status.STOPPED, "exited")],
)
async def test_reinstall_of_an_unfrozen_app_tears_down_without_unpausing(
    db, tmp_path, subprocess_mock, initial_status, container_state
):
    _app_dir(tmp_path, "plain_app")
    await _insert_app("plain_app", initial_status)

    with (
        settings_override({"path_root": str(tmp_path)}),
        _container_state(container_state),
        _reinstall_mocks(),
    ):
        await app_installation.reinstall_app("plain_app")
        await worker._reinstall_app("plain_app")

    commands = _issued_commands(subprocess_mock)
    assert _verbs(subprocess_mock)[0] == "down"
    assert commands[-1][-2:] == ("up", "--no-start")
    assert len(commands) == 2
    assert await _status("plain_app") == Status.STOPPED
