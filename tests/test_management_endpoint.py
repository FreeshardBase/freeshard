from httpx import AsyncClient

from shard_core.service.pairing import PairingCode
from tests.conftest import requires_test_env
from tests.util import wait_until_app_installed
from util import add_terminal


@requires_test_env("full")
async def test_install_app(api_client: AsyncClient, requests_mock):
    installed_apps = (await api_client.get("protected/apps")).json()
    assert not any(a["name"] == "mock_app" for a in installed_apps)

    response = await api_client.post(
        "management/apps/mock_app", headers={"authorization": "constantSharedSecret"}
    )
    response.raise_for_status()

    await wait_until_app_installed(api_client, "mock_app")

    installed_apps = (await api_client.get("protected/apps")).json()
    assert any(a["name"] == "mock_app" for a in installed_apps)


async def test_make_pairing_code(api_client: AsyncClient, requests_mock):
    pairing_code_response = await api_client.get(
        "management/pairing_code", headers={"authorization": "constantSharedSecret"}
    )
    pairing_code_response.raise_for_status()
    pairing_code = PairingCode.validate(pairing_code_response.json())

    add_terminal_response = await add_terminal(api_client, pairing_code.code, 'new_terminal')
    add_terminal_response.raise_for_status()
    assert add_terminal_response.status_code == 201
