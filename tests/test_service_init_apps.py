import gconf
from httpx import AsyncClient
from unittest.mock import AsyncMock

import shard_core.service.app_installation
from shard_core.database import database
from shard_core.service.app_installation import STORE_KEY_INITIAL_APPS_INSTALLED
from tests.conftest import requires_test_env
from tests.util import wait_until_all_apps_installed

init_app_conf = {"apps": {"initial_apps": ["filebrowser", "mock_app"]}}


async def test_refresh_init_apps_skipped_if_flag_set(db, mocker):
    await database.set_value(STORE_KEY_INITIAL_APPS_INSTALLED, True)
    mock_install = mocker.patch(
        "shard_core.service.app_installation.install_app_from_store",
        new_callable=AsyncMock,
    )

    with gconf.override_conf(init_app_conf):
        await shard_core.service.app_installation.refresh_init_apps()

    mock_install.assert_not_called()


async def test_refresh_init_apps_installs_on_first_startup(db, mocker):
    await database.remove_value(STORE_KEY_INITIAL_APPS_INSTALLED)
    mock_install = mocker.patch(
        "shard_core.service.app_installation.install_app_from_store",
        new_callable=AsyncMock,
    )

    with gconf.override_conf(init_app_conf):
        await shard_core.service.app_installation.refresh_init_apps()

    assert mock_install.call_count == len(init_app_conf["apps"]["initial_apps"])
    assert await database.get_value(STORE_KEY_INITIAL_APPS_INSTALLED) is True


@requires_test_env("full")
async def test_add_init_app(api_client: AsyncClient):
    response = await api_client.get("/protected/apps")
    response.raise_for_status()
    assert {j["name"] for j in response.json()} == {
        "filebrowser",
        "paperless-ngx",
        "immich",
    }

    # Clear the flag so refresh_init_apps() runs again (it was set during startup)
    await database.remove_value(STORE_KEY_INITIAL_APPS_INSTALLED)

    with gconf.override_conf(init_app_conf):
        await shard_core.service.app_installation.refresh_init_apps()
    await wait_until_all_apps_installed(api_client)

    response = await api_client.get("/protected/apps")
    response.raise_for_status()
    assert {j["name"] for j in response.json()} == {
        "filebrowser",
        "paperless-ngx",
        "immich",
        "mock_app",
    }
