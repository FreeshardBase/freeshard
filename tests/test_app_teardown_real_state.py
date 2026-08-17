"""Teardown decides its unpause from the real container state, not the stored
status (issue #199)."""

import asyncio
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


def _operations(subprocess_mock) -> list[tuple[str, ...]]:
    """(app project, compose operation…) per issued command, in order. The
    project is the `-p` value: a command aimed at the wrong app — or at the core
    stack, issue #160 — must not read the same as a correct one."""
    return [
        (c[c.index("-p") + 1], *c[c.index("--project-directory") + 2 :])
        for c in (call.args for call in subprocess_mock.await_args_list)
    ]


@contextmanager
def _patched_container_state(mock: AsyncMock):
    """Both the app_tools and the worker reference point at one mock, so a
    sequence of answers is shared across the teardown and the check that follows
    it."""
    with (
        patch.object(app_tools, "get_app_container_state", new=mock),
        patch.object(worker, "get_app_container_state", new=mock),
    ):
        yield


def _container_states(*states: str):
    """What the daemon reports, in order. The reinstall path asks twice: once to
    decide the unpause, once to confirm the old containers are really gone."""
    mock = (
        AsyncMock(return_value=states[0])
        if len(states) == 1
        else AsyncMock(side_effect=list(states))
    )
    return _patched_container_state(mock)


def _container_state_per_app(states: dict[str, str]):
    """Each app answers for itself — one shared answer would hide a teardown
    that probed a different app than the one it went on to tear down."""
    return _patched_container_state(AsyncMock(side_effect=lambda name: states[name]))


@pytest.mark.parametrize(
    "status", [Status.REINSTALLING, Status.ERROR, Status.RUNNING, Status.STOPPED]
)
async def test_shutdown_unpauses_a_frozen_stack_whatever_the_status_says(
    db, tmp_path, subprocess_mock, status
):
    _app_dir(tmp_path, "frozen_app")
    await _insert_app("frozen_app", status)

    with settings_override({"path_root": str(tmp_path)}), _container_states("paused"):
        await app_tools.docker_shutdown_app("frozen_app", force=True)

    assert _operations(subprocess_mock) == [
        ("frozen_app", "unpause"),
        ("frozen_app", "down"),
    ]


@pytest.mark.parametrize("container_state", ["running", "exited", "missing"])
async def test_shutdown_does_not_unpause_an_unfrozen_stack(
    db, tmp_path, subprocess_mock, container_state
):
    """ "missing" is also what a failing `compose ps` reports, so this covers the
    daemon-hiccup path as well."""
    _app_dir(tmp_path, "stopped_app")
    await _insert_app("stopped_app", Status.STOPPED)

    with (
        settings_override({"path_root": str(tmp_path)}),
        _container_states(container_state),
    ):
        await app_tools.docker_shutdown_app("stopped_app")

    assert _operations(subprocess_mock) == [("stopped_app", "down")]


@pytest.mark.parametrize("status", [Status.RUNNING, Status.UNINSTALLING])
async def test_stop_unpauses_a_frozen_stack_whose_status_is_not_paused(
    db, tmp_path, subprocess_mock, status
):
    _app_dir(tmp_path, "frozen_app")
    await _insert_app("frozen_app", status)

    with settings_override({"path_root": str(tmp_path)}), _container_states("paused"):
        await app_tools.docker_stop_app("frozen_app", set_status=False)

    assert _operations(subprocess_mock) == [
        ("frozen_app", "unpause"),
        ("frozen_app", "stop"),
    ]


async def test_stop_skips_an_app_whose_status_is_outside_its_allow_list(
    db, tmp_path, subprocess_mock
):
    """Unlike docker_shutdown_app, docker_stop_app has no force flag — its gate
    still rejects REINSTALLING, which is why the reinstall path forces the
    shutdown rather than relying on a stop."""
    _app_dir(tmp_path, "frozen_app")
    await _insert_app("frozen_app", Status.REINSTALLING)

    with settings_override({"path_root": str(tmp_path)}), _container_states("paused"):
        await app_tools.docker_stop_app("frozen_app")

    subprocess_mock.assert_not_called()


@pytest.mark.parametrize(
    "status", [Status.RUNNING, Status.PAUSED, Status.REINSTALLING, Status.ERROR]
)
async def test_shutdown_without_force_still_respects_its_allow_list(
    db, tmp_path, subprocess_mock, status
):
    """The allow-lists are what keep the idle control tick off an app that is
    mid-reinstall, so the fix forces the shutdown instead of widening them. A
    frozen stack outside the list must not even be unpaused: thawing it without
    a stop or down would page it back in for nothing."""
    _app_dir(tmp_path, "frozen_app")
    await _insert_app("frozen_app", status)

    with settings_override({"path_root": str(tmp_path)}), _container_states("paused"):
        await app_tools.docker_shutdown_app("frozen_app")

    subprocess_mock.assert_not_called()


async def test_stop_does_not_unpause_when_the_stack_is_not_frozen(
    db, tmp_path, subprocess_mock
):
    """The db can say PAUSED while the containers exited out-of-band — unpausing
    that stack fails, so the real state has to decide here too."""
    _app_dir(tmp_path, "exited_app")
    await _insert_app("exited_app", Status.PAUSED)

    with settings_override({"path_root": str(tmp_path)}), _container_states("exited"):
        await app_tools.docker_stop_app("exited_app")

    assert _operations(subprocess_mock) == [("exited_app", "stop")]
    assert await _status("exited_app") == Status.STOPPED


async def test_teardown_continues_with_down_when_unpause_fails(
    db, tmp_path, subprocess_mock
):
    """A partially-paused stack rejects unpause. Aborting the teardown there is
    exactly the failure this fix removes, so `down` must still be attempted."""
    _app_dir(tmp_path, "mixed_app")
    await _insert_app("mixed_app", Status.REINSTALLING)
    subprocess_mock.side_effect = [
        SubprocessError("Container mixed_app is not paused"),  # unpause
        "",  # down
    ]

    with settings_override({"path_root": str(tmp_path)}), _container_states("paused"):
        await app_tools.docker_shutdown_app("mixed_app", force=True)

    assert _operations(subprocess_mock) == [
        ("mixed_app", "unpause"),
        ("mixed_app", "down"),
    ]


async def test_shutdown_all_apps_removes_a_frozen_stack_with_a_stale_status(
    db, tmp_path, subprocess_mock
):
    """Core restart: docker_shutdown_all_apps(force=True) must remove a stack
    whose containers are paused but whose row says something else (issue #200).
    Two apps in different states, so a teardown that treats them alike shows."""
    _app_dir(tmp_path, "frozen_app")
    _app_dir(tmp_path, "other_app")
    await _insert_app("frozen_app", Status.ERROR)
    await _insert_app("other_app", Status.STOPPED)

    with (
        settings_override({"path_root": str(tmp_path)}),
        _container_state_per_app({"frozen_app": "paused", "other_app": "exited"}),
    ):
        await app_tools.docker_shutdown_all_apps(force=True)

    operations = _operations(subprocess_mock)
    assert sorted(operations) == [
        ("frozen_app", "down"),
        ("frozen_app", "unpause"),
        ("other_app", "down"),
    ]
    assert operations.index(("frozen_app", "unpause")) < operations.index(
        ("frozen_app", "down")
    )
    assert await _status("frozen_app") == Status.DOWN
    assert await _status("other_app") == Status.DOWN


@contextmanager
def _reinstall_mocks():
    """Stub out everything the reinstall does besides driving docker. The fake
    download must recreate the app dir and its compose file: _reinstall_app has
    just rmtree'd them, and every later compose call resolves through
    app_compose_command, which raises without a compose file."""

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
    ):
        yield


async def test_reinstall_removes_frozen_containers_before_creating_new_ones(
    db, tmp_path, subprocess_mock
):
    """The #199 regression: the old stack outlived the reinstall, so
    `compose up --no-start` ran against paused containers and errored out."""
    _app_dir(tmp_path, "frozen_app")
    await _insert_app("frozen_app", Status.REINSTALLATION_QUEUED)

    with (
        settings_override({"path_root": str(tmp_path)}),
        _container_states("paused", "missing"),
        _reinstall_mocks(),
    ):
        await worker._reinstall_app("frozen_app")

    assert _operations(subprocess_mock) == [
        ("frozen_app", "unpause"),
        ("frozen_app", "down"),
        ("frozen_app", "up", "--no-start"),
    ]
    assert await _status("frozen_app") == Status.STOPPED


@pytest.mark.parametrize("container_state", ["running", "exited", "missing"])
async def test_reinstall_of_an_unfrozen_app_tears_down_before_creating(
    db, tmp_path, subprocess_mock, container_state
):
    _app_dir(tmp_path, "plain_app")
    await _insert_app("plain_app", Status.REINSTALLATION_QUEUED)

    with (
        settings_override({"path_root": str(tmp_path)}),
        _container_states(container_state, "missing"),
        _reinstall_mocks(),
    ):
        await worker._reinstall_app("plain_app")

    assert _operations(subprocess_mock) == [
        ("plain_app", "down"),
        ("plain_app", "up", "--no-start"),
    ]
    assert await _status("plain_app") == Status.STOPPED


async def test_reinstall_keeps_the_old_app_when_containers_survive_the_teardown(
    db, tmp_path, subprocess_mock
):
    """A teardown that did not actually remove the stack must not delete the app
    directory: recreating over surviving containers is the #199 damage, and the
    old install is the only thing the user still has."""
    app_dir = _app_dir(tmp_path, "stuck_app")
    await _insert_app("stuck_app", Status.REINSTALLATION_QUEUED)

    with (
        settings_override({"path_root": str(tmp_path)}),
        _container_states("paused", "paused"),
        _reinstall_mocks(),
    ):
        await worker._reinstall_app("stuck_app")

    assert _operations(subprocess_mock) == [
        ("stuck_app", "unpause"),
        ("stuck_app", "down"),
    ]
    assert (app_dir / "docker-compose.yml").exists()
    assert await _status("stuck_app") == Status.ERROR


async def test_reinstall_is_serialized_by_the_per_app_op_lock(
    db, tmp_path, subprocess_mock
):
    """The reinstall now really removes containers, so it must hold the same lock
    the uninstall does — otherwise a wake-on-access revive can recreate the stack
    between the teardown and the rmtree (issue #185)."""
    _app_dir(tmp_path, "reinstall_locked_app")
    await _insert_app("reinstall_locked_app", Status.REINSTALLATION_QUEUED)

    lock = app_tools.app_op_lock("reinstall_locked_app")
    with (
        settings_override({"path_root": str(tmp_path)}),
        _container_states("paused", "missing"),
        _reinstall_mocks(),
    ):
        await lock.acquire()
        try:
            task = asyncio.create_task(worker._reinstall_app("reinstall_locked_app"))
            await asyncio.sleep(0.05)
            assert not task.done()
            subprocess_mock.assert_not_called()
            assert await _status("reinstall_locked_app") == Status.REINSTALLATION_QUEUED
        finally:
            lock.release()
        await asyncio.wait_for(task, timeout=1)

    assert await _status("reinstall_locked_app") == Status.STOPPED


async def test_teardown_left_containers_tolerates_a_missing_compose_file(
    db, tmp_path, subprocess_mock
):
    """An app dir without a rendered compose file cannot be probed through
    compose at all. Report no leftovers so the reinstall re-downloads it rather
    than refusing to repair the app forever."""
    app_dir = tmp_path / "core" / "installed_apps" / "no_compose_app"
    app_dir.mkdir(parents=True)

    with settings_override({"path_root": str(tmp_path)}):
        assert await worker._teardown_left_containers("no_compose_app") is False

    subprocess_mock.assert_not_called()


async def test_reinstall_of_an_errored_app_is_queued(db, tmp_path):
    """A shard already broken by #199 sits in ERROR, and the reinstall that
    repairs it has to be accepted from there — the worker only ever sees
    REINSTALLATION_QUEUED, so this is where that criterion is decided."""
    _app_dir(tmp_path, "broken_app")
    await _insert_app("broken_app", Status.ERROR)

    with (
        settings_override({"path_root": str(tmp_path)}),
        patch.object(
            installation_util, "app_exists_in_store", new=AsyncMock(return_value=True)
        ),
    ):
        await app_installation.reinstall_app("broken_app")

    queued = worker.installation_worker._task_queue.get_nowait()
    assert queued.task_type == "reinstall"
    assert await _status("broken_app") == Status.REINSTALLATION_QUEUED
