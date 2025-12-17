import docker
import pytest
from docker.errors import NotFound
from fastapi import status
from httpx import AsyncClient

from tests.conftest import requires_test_env
from tests.util import (
    wait_until_app_installed,
    mock_app_store_path,
    wait_until_app_uninstalled,
)

pytest_plugins = ("pytest_asyncio",)
pytestmark = pytest.mark.asyncio


@requires_test_env("full")
async def test_get_initial_apps(api_client: AsyncClient):
    response = (await api_client.get("protected/apps")).json()
    assert len(response) == 3
    assert "filebrowser" in [e["name"] for e in response]


@requires_test_env("full")
async def test_install_app(api_client: AsyncClient):
    docker_client = docker.from_env()
    app_name = "mock_app"

    response = await api_client.post(f"protected/apps/{app_name}")
    assert response.status_code == status.HTTP_201_CREATED

    await wait_until_app_installed(api_client, app_name)

    docker_client.containers.get(app_name)

    response = (await api_client.get("protected/apps")).json()
    assert len(response) == 4


@requires_test_env("full")
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


@requires_test_env("full")
async def test_install_app_twice(api_client: AsyncClient):
    app_name = "mock_app"

    response = await api_client.post(f"protected/apps/{app_name}")
    assert response.status_code == status.HTTP_201_CREATED

    await wait_until_app_installed(api_client, app_name)

    response = await api_client.post(f"protected/apps/{app_name}")
    assert response.status_code == status.HTTP_409_CONFLICT


@requires_test_env("full")
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


@requires_test_env("full")
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


@requires_test_env("full")
async def test_install_custom_app(api_client: AsyncClient):
    app_name = "mock_app"
    docker_client = docker.from_env()

    app_zip = mock_app_store_path() / app_name / f"{app_name}.zip"
    with open(app_zip, "rb") as f:
        content = f.read()
    response = await api_client.post(
        "protected/apps",
        files={"file": (f"{app_name}.zip", content, "application/zip")},
    )
    assert response.status_code == status.HTTP_201_CREATED

    await wait_until_app_installed(api_client, app_name)

    docker_client.containers.get(app_name)

    response = (await api_client.get("protected/apps")).json()
    assert len(response) == 4
