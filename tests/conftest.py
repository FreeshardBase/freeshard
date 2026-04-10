import os

os.environ.setdefault("CONFIG", "tests/config.toml")

import asyncio
import importlib
import json
import logging
import re
import shutil
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta
from logging import LogRecord
from pathlib import Path
from typing import List, AsyncGenerator

import psycopg
import pytest
import pytest_asyncio
import responses
import yappi
from asgi_lifespan import LifespanManager
from httpx import AsyncClient, ASGITransport
from requests import PreparedRequest
from responses import RequestsMock

from shard_core.data_model.app_meta import VMSize
from shard_core.data_model.backend.shard_model import (
    ShardStatus,
    VmSize,
    ShardDb,
    Cloud,
)
from shard_core import app_factory
from shard_core.data_model.identity import OutputIdentity, Identity
from shard_core.data_model.profile import Profile
from shard_core.database import database
from shard_core.service import websocket, app_installation, telemetry
from shard_core.service.app_tools import get_installed_apps_path
from shard_core.settings import Settings, set_settings, reset_settings
from shard_core.web.internal.call_peer import _get_app_for_ip_address
from tests.util import (
    docker_network_portal,
    wait_until_all_apps_installed,
    mock_app_store_path,
)

pytest_plugins = ("pytest_asyncio",)


class _TestSettings(Settings):
    """Settings subclass that loads config.toml with tests/config.toml as overlay."""

    @classmethod
    def _override_toml_files(cls) -> list[str]:
        return ["tests/config.toml"]


def _apply_model_dict(base, override: dict):
    """Recursively apply a dict of overrides to a pydantic model."""
    update = {}
    for key, value in override.items():
        current = getattr(base, key, None)
        if (
            isinstance(value, dict)
            and current is not None
            and hasattr(current, "model_copy")
        ):
            update[key] = _apply_model_dict(current, value)
        else:
            update[key] = value
    return base.model_copy(update=update)


@contextmanager
def settings_override(override: dict):
    """Context manager to temporarily apply a nested dict override to settings."""
    from shard_core.settings import settings

    old = settings()
    set_settings(_apply_model_dict(old, override))
    try:
        yield
    finally:
        set_settings(old)


@pytest.fixture(scope="session")
def docker_compose_file():
    return str(Path(__file__).parent / "docker-compose.yml")


@pytest.fixture(scope="session")
def docker_compose_project_name():
    return "shard-core-test"


def is_responsive(conninfo):
    try:
        conn = psycopg.connect(conninfo)
        conn.close()
        return True
    except psycopg.OperationalError:
        return False


@pytest.fixture(scope="session")
def postgres_db(docker_services):
    """Start Postgres via pytest-docker and wait until it is responsive."""
    port = docker_services.port_for("postgres", 5432)
    conninfo = f"host=localhost port={port} dbname=shard_core_test user=shard_core_test password=shard_core_test"
    docker_services.wait_until_responsive(
        timeout=30.0,
        pause=0.5,
        check=lambda: is_responsive(conninfo),
    )
    return {
        "host": "localhost",
        "port": port,
        "dbname": "shard_core_test",
        "user": "shard_core_test",
        "password": "shard_core_test",
    }


@pytest.fixture(autouse=True, scope="session")
def setup_all(postgres_db):
    asyncio.run(app_installation.login_docker_registries())


@pytest.fixture(autouse=True)
def config_override(tmp_path, request, postgres_db):
    print(f"\nUsing temp path: {tmp_path}")

    # Detects the variable named *config_override* of a test module
    module_override = getattr(request.module, "config_override", {})

    # Detects the annotation named @pytest.mark.config_override of a test function
    function_override_mark = request.node.get_closest_marker("config_override")
    function_override = function_override_mark.args[0] if function_override_mark else {}

    _truncate_all_tables(postgres_db)

    base = _TestSettings(
        path_root=str(tmp_path / "path_root"),
        db=postgres_db,
    )
    combined = _apply_model_dict(base, {**module_override, **function_override})
    set_settings(combined)

    yield

    reset_settings()


def _truncate_all_tables(postgres_db: dict):
    conninfo = (
        f"host={postgres_db['host']} port={postgres_db['port']} "
        f"dbname={postgres_db['dbname']} user={postgres_db['user']} password={postgres_db['password']}"
    )
    with psycopg.connect(conninfo, autocommit=True) as conn:
        rows = conn.execute(
            "SELECT tablename FROM pg_tables WHERE schemaname = 'public'"
        ).fetchall()
        tables = [r[0] for r in rows if not r[0].startswith("_yoyo")]
        if tables:
            conn.execute(f"TRUNCATE {', '.join(tables)} RESTART IDENTITY CASCADE")


@pytest_asyncio.fixture
async def db():
    """Initialize and tear down the database for tests that don't use api_client."""
    await database.init_database()
    yield
    await database.shutdown_database()


@pytest_asyncio.fixture
async def api_client(requests_mock, mocker) -> AsyncGenerator[AsyncClient]:
    # Modules that define some global state need to be reloaded
    importlib.reload(websocket)
    importlib.reload(app_installation.worker)
    importlib.reload(telemetry)

    # Mocks must be set up after modules are reloaded or else they will be overwritten
    mock_app_store(mocker)

    async def noop():
        pass

    mocker.patch("shard_core.service.app_installation.login_docker_registries", noop)

    async with docker_network_portal():
        app = app_factory.create_app()
        async with (
            LifespanManager(app, startup_timeout=20),
            AsyncClient(
                transport=ASGITransport(app=app), base_url="https://init", timeout=20
            ) as client,
        ):
            whoareyou = (await client.get("/public/meta/whoareyou")).json()
            client.base_url = f'https://{whoareyou["domain"]}'
            await wait_until_all_apps_installed(client)
            yield client


@pytest_asyncio.fixture
async def app_client(mocker) -> AsyncGenerator[AsyncClient]:
    """Lightweight fixture that creates the FastAPI app WITHOUT running the lifespan.

    Database is initialized directly (no Docker network needed).
    """
    importlib.reload(websocket)
    importlib.reload(app_installation.worker)
    importlib.reload(telemetry)

    # Initialize the database (migrations + pool) and create default identity
    await database.init_database()
    from shard_core.service import identity

    await identity.init_default_identity()

    app = app_factory.create_app()

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="https://init", timeout=10
    ) as client:
        whoareyou = (await client.get("/public/meta/whoareyou")).json()
        client.base_url = f'https://{whoareyou["domain"]}'
        yield client

    await database.shutdown_database()


mock_profile = Profile(
    vm_id="shard_foobar",
    owner="test owner",
    owner_email="testowner@foobar.com",
    time_created=datetime.now() - timedelta(days=2),
    time_assigned=datetime.now() - timedelta(days=1),
    vm_size=VMSize.XS,
    max_vm_size=VMSize.M,
)

mock_shard = ShardDb(
    id=2,
    machine_id="shard_foobar",
    owner_name="test owner",
    owner_email="testowner@foobar.com",
    time_created=datetime.now() - timedelta(days=2),
    time_assigned=datetime.now() - timedelta(days=1),
    vm_size=VmSize.XS,
    max_vm_size=VmSize.M,
    status=ShardStatus.ASSIGNED,
    shared_secret="foosecretbar",
    cloud=Cloud.OVHCLOUD,
)


@contextmanager
def requests_mock_context(*, shard: ShardDb = None, profile: Profile = None):
    from shard_core.settings import settings

    management_api = "https://management-mock"
    controller_base_url = "https://freeshard-controller-mock"
    management_shared_secret = "constantSharedSecret"

    old_settings = settings()
    new_settings = old_settings.model_copy(
        update={
            "management": old_settings.management.model_copy(
                update={"api_url": management_api}
            ),
            "freeshard_controller": old_settings.freeshard_controller.model_copy(
                update={"base_url": controller_base_url}
            ),
        }
    )
    set_settings(new_settings)

    try:
        with responses.RequestsMock(assert_all_requests_are_fired=False) as rsps:
            rsps.add_callback(
                responses.POST,
                f"{controller_base_url}/api/shards/self/resize",
                callback=requests_mock_resize,
            )
            rsps.post(f"{management_api}/app_usage")
            rsps.get(
                f"{management_api}/sharedSecret",
                body=json.dumps({"shared_secret": management_shared_secret}),
            )
            rsps.get(
                f"{controller_base_url}/api/shards/self",
                body=(shard or mock_shard).model_dump_json(),
            )
            rsps.post(f"{controller_base_url}/api/feedback")
            rsps.get(f"{controller_base_url}/api/foo")
            rsps.add_passthru("")
            yield rsps
    finally:
        set_settings(old_settings)


def requests_mock_resize(request: PreparedRequest):
    data = json.loads(request.body)
    if data["new_vm_size"] in ["l", "xl"]:
        return 409, {}, ""
    else:
        return 204, {}, ""


@pytest.fixture
def requests_mock():
    with requests_mock_context() as c:
        yield c


@pytest.fixture
def peer_mock_requests(mocker):
    mocker.patch(
        "shard_core.web.internal.call_peer._get_app_for_ip_address",
        lambda x: "mock_app",
    )
    _get_app_for_ip_address.cache_clear()
    peer_identity = Identity.create("mock peer")
    print(f"mocking peer {peer_identity.short_id}")
    base_url = f"https://{peer_identity.domain}/core"
    app_url = f"https://mock_app.{peer_identity.domain}"

    with responses.RequestsMock(assert_all_requests_are_fired=False) as rsps:
        rsps.get(
            base_url + "/public/meta/whoareyou",
            json=OutputIdentity(**peer_identity.model_dump()).model_dump(),
        )
        rsps.get(re.compile(app_url + "/.*"))
        rsps.post(re.compile(app_url + "/.*"))

        rsps.add_passthru("")

        yield PeerMockRequests(
            peer_identity,
            rsps,
        )

    _get_app_for_ip_address.cache_clear()


def mock_app_store(mocker):
    async def mock_download_app_zip(name: str, _=None) -> Path:
        source_zip = mock_app_store_path() / name / f"{name}.zip"
        target_zip = get_installed_apps_path() / name / f"{name}.zip"
        target_zip.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(source_zip, target_zip.parent)
        print(f"downloaded {name} to {target_zip}")
        return target_zip

    mocker.patch(
        "shard_core.service.app_installation.worker._download_app_zip",
        mock_download_app_zip,
    )

    async def mock_app_exists_in_store(name: str) -> bool:
        source_zip = mock_app_store_path() / name / f"{name}.zip"
        return source_zip.exists()

    mocker.patch(
        "shard_core.service.app_installation.util.app_exists_in_store",
        mock_app_exists_in_store,
    )


@pytest.fixture
def profile_with_yappi():
    yappi.set_clock_type("WALL")
    with yappi.run():
        yield
    yappi.get_func_stats().print_all()


@dataclass
class PeerMockRequests:
    identity: Identity
    mock: RequestsMock


class MemoryLogHandler(logging.Handler):
    def __init__(self):
        super().__init__()
        self.records: List[LogRecord] = []

    def emit(self, record):
        self.records.append(record)


@pytest.fixture
def memory_logger():
    memory_handler = MemoryLogHandler()
    root_logger = logging.getLogger()
    root_logger.addHandler(memory_handler)
    yield memory_handler
    root_logger.removeHandler(memory_handler)
