import io
import zipfile

import docker
import pytest
from docker.errors import NotFound
from fastapi import status
from httpx import AsyncClient

from shard_core.data_model.app_meta import InstallationReason, InstalledApp, Status
from shard_core.database import installed_apps as db_installed_apps
from shard_core.database.connection import db_conn
from shard_core.service.app_tools import get_installed_apps_path
from tests.util import (
    wait_until_app_installed,
    mock_app_store_path,
    wait_until_app_uninstalled,
)

pytest_plugins = ("pytest_asyncio",)
pytestmark = pytest.mark.asyncio


async def test_get_initial_apps(api_client: AsyncClient):
    response = (await api_client.get("protected/apps")).json()
    assert len(response) == 3
    assert "filebrowser" in [e["name"] for e in response]


async def test_install_app(api_client: AsyncClient):
    docker_client = docker.from_env()
    app_name = "mock_app"

    response = await api_client.post(f"protected/apps/{app_name}")
    assert response.status_code == status.HTTP_201_CREATED

    await wait_until_app_installed(api_client, app_name)

    docker_client.containers.get(app_name)

    response = (await api_client.get("protected/apps")).json()
    assert len(response) == 4


async def test_reinstall_app(api_client: AsyncClient):
    app_name = "mock_app"

    response = await api_client.post(f"protected/apps/{app_name}")
    assert response.status_code == status.HTTP_201_CREATED

    await wait_until_app_installed(api_client, app_name)
    response = (await api_client.get("protected/apps")).json()
    assert len(response) == 4

    response = await api_client.post(f"protected/apps/{app_name}/reinstall")
    assert response.status_code == status.HTTP_201_CREATED

    await wait_until_app_installed(api_client, app_name)
    response = (await api_client.get("protected/apps")).json()
    assert len(response) == 4


async def test_install_app_twice(api_client: AsyncClient):
    app_name = "mock_app"

    response = await api_client.post(f"protected/apps/{app_name}")
    assert response.status_code == status.HTTP_201_CREATED

    await wait_until_app_installed(api_client, app_name)

    response = await api_client.post(f"protected/apps/{app_name}")
    assert response.status_code == status.HTTP_409_CONFLICT


async def test_uninstall_app(api_client: AsyncClient):
    docker_client = docker.from_env()
    docker_client.containers.get("filebrowser")

    response = await api_client.delete("protected/apps/filebrowser")
    assert response.status_code == status.HTTP_204_NO_CONTENT

    await wait_until_app_uninstalled(api_client, "filebrowser")

    response = (await api_client.get("protected/apps")).json()
    assert len(response) == 2

    with pytest.raises(NotFound):
        docker_client.containers.get("filebrowser")


async def test_uninstall_running_app(api_client: AsyncClient):
    docker_client = docker.from_env()
    app_name = "mock_app"

    response = await api_client.post(f"protected/apps/{app_name}")
    assert response.status_code == status.HTTP_201_CREATED

    await wait_until_app_installed(api_client, app_name)

    # Start the app
    response = await api_client.get(
        "internal/auth",
        headers={
            "X-Forwarded-Host": f"{app_name}.myshard.org",
            "X-Forwarded-Uri": "/pub",
        },
    )
    response.raise_for_status()

    response = await api_client.delete(f"protected/apps/{app_name}")
    assert response.status_code == status.HTTP_204_NO_CONTENT

    await wait_until_app_uninstalled(api_client, app_name)

    response = (await api_client.get("protected/apps")).json()
    assert len(response) == 3  # Initial apps are still installed

    with pytest.raises(NotFound):
        docker_client.containers.get(app_name)


async def test_uninstall_app_without_compose_file(api_client: AsyncClient):
    app_name = "mock_app"
    async with db_conn() as conn:
        await db_installed_apps.insert(
            conn,
            InstalledApp(
                name=app_name,
                installation_reason=InstallationReason.CUSTOM,
                status=Status.ERROR,
            ).model_dump(),
        )
    (get_installed_apps_path() / app_name).mkdir(parents=True, exist_ok=True)

    response = await api_client.delete(f"protected/apps/{app_name}")
    assert response.status_code == status.HTTP_204_NO_CONTENT

    await wait_until_app_uninstalled(api_client, app_name)
    assert not (get_installed_apps_path() / app_name).exists()


async def _upload_custom_app(api_client: AsyncClient, filename: str, content: bytes):
    return await api_client.post(
        "protected/apps",
        files={"file": (filename, content, "application/zip")},
    )


def _mock_app_zip_bytes() -> bytes:
    return (mock_app_store_path() / "mock_app" / "mock_app.zip").read_bytes()


def _nested_mock_app_zip_bytes() -> bytes:
    """The mock_app zip, but with all files inside a single top-level directory."""
    buffer = io.BytesIO()
    with zipfile.ZipFile(io.BytesIO(_mock_app_zip_bytes())) as source:
        with zipfile.ZipFile(buffer, "w") as target:
            for name in source.namelist():
                target.writestr(f"mock_app/{name}", source.read(name))
    return buffer.getvalue()


async def test_install_custom_app(api_client: AsyncClient):
    app_name = "mock_app"
    docker_client = docker.from_env()

    response = await _upload_custom_app(
        api_client, f"{app_name}.zip", _mock_app_zip_bytes()
    )
    assert response.status_code == status.HTTP_201_CREATED

    await wait_until_app_installed(api_client, app_name)

    docker_client.containers.get(app_name)

    response = (await api_client.get("protected/apps")).json()
    assert len(response) == 4


async def test_install_custom_app_uses_name_from_app_meta(api_client: AsyncClient):
    response = await _upload_custom_app(
        api_client, "some-unrelated-filename.zip", _mock_app_zip_bytes()
    )
    assert response.status_code == status.HTTP_201_CREATED

    await wait_until_app_installed(api_client, "mock_app")

    response = await api_client.get("protected/apps/some-unrelated-filename")
    assert response.status_code == status.HTTP_404_NOT_FOUND


async def test_install_custom_app_with_single_top_level_dir(api_client: AsyncClient):
    app_name = "mock_app"
    docker_client = docker.from_env()

    response = await _upload_custom_app(
        api_client, f"{app_name}.zip", _nested_mock_app_zip_bytes()
    )
    assert response.status_code == status.HTTP_201_CREATED

    await wait_until_app_installed(api_client, app_name)

    docker_client.containers.get(app_name)
    app = (await api_client.get(f"protected/apps/{app_name}")).json()
    assert app["meta"]["name"] == app_name


async def test_install_custom_app_without_app_meta(api_client: AsyncClient):
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as zip_ref:
        zip_ref.writestr("docker-compose.yml.template", "services: {}")

    response = await _upload_custom_app(api_client, "mock_app.zip", buffer.getvalue())
    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert "app_meta.json is missing" in response.json()["detail"]

    assert len((await api_client.get("protected/apps")).json()) == 3
    assert not (get_installed_apps_path() / "mock_app").exists()


async def test_install_custom_app_that_is_not_a_zip(api_client: AsyncClient):
    response = await _upload_custom_app(api_client, "mock_app.zip", b"not a zip file")
    assert response.status_code == status.HTTP_400_BAD_REQUEST

    assert len((await api_client.get("protected/apps")).json()) == 3
    assert not (get_installed_apps_path() / "mock_app").exists()
