import shutil
import string

import pytest
import yaml

from shard_core.data_model.app_meta import InstallationReason, InstalledApp, Status
from shard_core.database import app_secrets as db_app_secrets
from shard_core.database import installed_apps as db_installed_apps
from shard_core.database.connection import db_conn
from shard_core.service import identity
from shard_core.service.app_installation.app_secrets import generate_secret
from shard_core.service.app_installation.util import render_docker_compose_template
from shard_core.service.app_installation.worker import _uninstall_app
from shard_core.service.app_tools import get_installed_apps_path

pytestmark = pytest.mark.asyncio

_SECRET_CHARS = set(string.ascii_letters + string.digits)


async def _install_app_with_template(app_name: str, template: str) -> InstalledApp:
    app = InstalledApp(
        name=app_name,
        installation_reason=InstallationReason.CUSTOM,
        status=Status.STOPPED,
    )
    async with db_conn() as conn:
        await db_installed_apps.insert(conn, app.model_dump())
    app_dir = get_installed_apps_path() / app_name
    app_dir.mkdir(parents=True, exist_ok=True)
    (app_dir / "docker-compose.yml.template").write_text(template)
    return app


def _rendered_env(app_name: str) -> dict:
    rendered = (get_installed_apps_path() / app_name / "docker-compose.yml").read_text()
    return yaml.safe_load(rendered)["services"]["app"]["environment"]


@pytest.fixture(autouse=True)
async def default_identity(db):
    await identity.init_default_identity()


_TEMPLATE = """
services:
    app:
        image: nginx:alpine
        environment:
            PASSWORD: "{{ secret('db_password') }}"
"""


async def test_secret_generated_persisted_and_injected():
    app = await _install_app_with_template("secret_app", _TEMPLATE)

    await render_docker_compose_template(app)

    injected = _rendered_env("secret_app")["PASSWORD"]
    assert len(injected) == 32
    assert set(injected) <= _SECRET_CHARS

    async with db_conn() as conn:
        stored = await db_app_secrets.get_all_for_app(conn, "secret_app")
    assert stored == {"db_password": injected}


async def test_secret_reused_across_renders():
    app = await _install_app_with_template("reuse_app", _TEMPLATE)

    await render_docker_compose_template(app)
    first = _rendered_env("reuse_app")["PASSWORD"]

    await render_docker_compose_template(app)
    second = _rendered_env("reuse_app")["PASSWORD"]

    assert first == second


async def test_secret_reused_after_reinstall():
    # Intent (issue #138): reinstall reuses the kept secret. A reinstall wipes
    # the app dir (worker._reinstall_app) but leaves the DB row and app_secrets.
    app = await _install_app_with_template("reinstall_app", _TEMPLATE)
    await render_docker_compose_template(app)
    first = _rendered_env("reinstall_app")["PASSWORD"]

    app_dir = get_installed_apps_path() / "reinstall_app"
    shutil.rmtree(app_dir)
    app_dir.mkdir(parents=True)
    (app_dir / "docker-compose.yml.template").write_text(_TEMPLATE)

    await render_docker_compose_template(app)
    assert _rendered_env("reinstall_app")["PASSWORD"] == first


async def test_distinct_names_get_distinct_secrets():
    template = """
services:
    app:
        image: nginx:alpine
        environment:
            A: "{{ secret('one') }}"
            B: "{{ secret('two') }}"
            A_AGAIN: "{{ secret('one') }}"
"""
    app = await _install_app_with_template("multi_app", template)

    await render_docker_compose_template(app)
    env = _rendered_env("multi_app")

    assert env["A"] == env["A_AGAIN"]
    assert env["A"] != env["B"]

    async with db_conn() as conn:
        stored = await db_app_secrets.get_all_for_app(conn, "multi_app")
    assert stored == {"one": env["A"], "two": env["B"]}


async def test_secrets_kept_on_uninstall(mocker):
    # Intent (issue #138): keep secrets on uninstall so reinstalling the same app
    # reuses them, matching its retained user_data.
    mocker.patch(
        "shard_core.service.app_installation.worker.docker_stop_app",
        mocker.AsyncMock(),
    )
    mocker.patch(
        "shard_core.service.app_installation.worker.docker_shutdown_app",
        mocker.AsyncMock(),
    )

    app = await _install_app_with_template("kept_app", _TEMPLATE)
    await render_docker_compose_template(app)
    async with db_conn() as conn:
        before = await db_app_secrets.get_all_for_app(conn, "kept_app")
    assert before

    await _uninstall_app("kept_app")

    async with db_conn() as conn:
        after = await db_app_secrets.get_all_for_app(conn, "kept_app")
    assert after == before


async def test_secrets_are_app_scoped():
    app_a = await _install_app_with_template("app_a", _TEMPLATE)
    app_b = await _install_app_with_template("app_b", _TEMPLATE)

    await render_docker_compose_template(app_a)
    await render_docker_compose_template(app_b)

    secret_a = _rendered_env("app_a")["PASSWORD"]
    secret_b = _rendered_env("app_b")["PASSWORD"]
    assert secret_a != secret_b

    async with db_conn() as conn:
        assert await db_app_secrets.get_all_for_app(conn, "app_a") == {
            "db_password": secret_a
        }
        assert await db_app_secrets.get_all_for_app(conn, "app_b") == {
            "db_password": secret_b
        }


async def test_no_secrets_persisted_for_secret_free_template():
    template = """
services:
    app:
        image: nginx:alpine
        volumes:
            - "{{ fs.app_data }}:/data"
"""
    app = await _install_app_with_template("plain_app", template)

    await render_docker_compose_template(app)

    assert (get_installed_apps_path() / "plain_app" / "docker-compose.yml").exists()
    async with db_conn() as conn:
        assert await db_app_secrets.get_all_for_app(conn, "plain_app") == {}


async def test_render_aborts_without_writing_file_when_persist_fails(mocker):
    mocker.patch(
        "shard_core.service.app_installation.util.persist_new_secrets",
        mocker.AsyncMock(side_effect=RuntimeError("db down")),
    )
    app = await _install_app_with_template("fail_app", _TEMPLATE)

    with pytest.raises(RuntimeError):
        await render_docker_compose_template(app)

    assert not (get_installed_apps_path() / "fail_app" / "docker-compose.yml").exists()


async def test_insert_is_idempotent():
    async with db_conn() as conn:
        await db_installed_apps.insert(
            conn,
            InstalledApp(
                name="idem_app",
                installation_reason=InstallationReason.CUSTOM,
                status=Status.STOPPED,
            ).model_dump(),
        )
        await db_app_secrets.insert(conn, "idem_app", "k", "first")
        await db_app_secrets.insert(conn, "idem_app", "k", "second")
        stored = await db_app_secrets.get_all_for_app(conn, "idem_app")
    assert stored == {"k": "first"}


async def test_generate_secret_length_charset_and_uniqueness():
    values = [generate_secret() for _ in range(100)]
    for v in values:
        assert len(v) == 32
        assert set(v) <= _SECRET_CHARS
    # distinct values across 100 draws → the generator is actually random,
    # not returning a constant.
    assert len(set(values)) == 100
