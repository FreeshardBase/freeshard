from time import sleep

from httpx import AsyncClient
from starlette import status
from tinydb.operations import delete

from shard_core.data_model.backend.shard_model import ShardDb
from shard_core.database.database import terminals_table
from shard_core.data_model.terminal import Terminal, Icon
from tests.conftest import requests_mock_context, mock_shard, requires_test_env
from tests.util import get_pairing_code, add_terminal, pair_new_terminal


@requires_test_env("full")
async def _delete_terminal(api_client: AsyncClient, t_id):
    return await api_client.delete(f"protected/terminals/id/{t_id}")


@requires_test_env("full")
async def test_add_delete(api_client: AsyncClient):
    t_name = "T1"
    await pair_new_terminal(api_client, t_name)

    response = await api_client.get(f"protected/terminals/name/{t_name}")
    assert response.status_code == 200
    t_id = response.json()["id"]

    response = await _delete_terminal(api_client, t_id)
    assert response.status_code == 204

    response = await api_client.get("protected/terminals")
    assert len(response.json()) == 0


@requires_test_env("full")
async def test_edit(api_client: AsyncClient):
    t_name_1 = "T1"
    await pair_new_terminal(api_client, t_name_1)
    response = await api_client.get(f"protected/terminals/name/{t_name_1}")
    assert response.status_code == 200
    response_terminal = Terminal(**response.json())
    assert response_terminal.name == t_name_1
    assert response_terminal.icon == Icon.UNKNOWN

    response_terminal.name = "T2"
    response_terminal.icon = Icon.NOTEBOOK
    response = await api_client.put(
        f"protected/terminals/id/{response_terminal.id}", data=response_terminal.json()
    )
    assert response.status_code == 200
    response = await api_client.get(f"protected/terminals/id/{response_terminal.id}")
    assert response.status_code == 200
    assert Terminal(**response.json()).name == response_terminal.name
    assert Terminal(**response.json()).icon == response_terminal.icon


@requires_test_env("full")
async def test_pairing_happy(api_client: AsyncClient, requests_mock):
    t_name = "T1"
    await pair_new_terminal(api_client, t_name)

    # was the terminal created with the correct data?
    response = await api_client.get("protected/terminals/name/T1")
    assert response.status_code == 200
    assert response.json()["name"] == t_name
    terminal_id = response.json()["id"]

    # can the terminal be authenticated using its jwt token?
    response = await api_client.get("internal/authenticate_terminal")
    assert response.status_code == status.HTTP_200_OK
    assert response.headers["X-Ptl-Client-Type"] == "terminal"
    assert response.headers["X-Ptl-Client-Id"] == terminal_id
    assert response.headers["X-Ptl-Client-Name"] == t_name

    # does whoami return the correct values?
    response = await api_client.get("public/meta/whoami")
    assert response.status_code == status.HTTP_200_OK
    assert response.json()["type"] == "terminal"
    assert response.json()["id"] == terminal_id
    assert response.json()["name"] == t_name

    # has the default identity been update from the profile?
    assert len(requests_mock.calls) == 1
    response = await api_client.get("protected/identities/default")
    assert response.status_code == status.HTTP_200_OK
    assert response.json()["name"] == "test owner"
    assert response.json()["email"] == "testowner@foobar.com"


@requires_test_env("full")
async def test_pairing_two(api_client: AsyncClient):
    t1_name = "T1"
    t2_name = "T2"
    await pair_new_terminal(api_client, t1_name)
    await pair_new_terminal(api_client, t2_name)

    response = await api_client.get("protected/terminals")
    assert len(response.json()) == 2


@requires_test_env("full")
async def test_pairing_two_with_same_name(api_client: AsyncClient):
    t1_name = "T1"
    await pair_new_terminal(api_client, t1_name)
    await pair_new_terminal(api_client, t1_name)

    response = await api_client.get("protected/terminals")
    assert len(response.json()) == 2


@requires_test_env("full")
async def test_pairing_no_code(api_client: AsyncClient):
    response = await add_terminal(api_client, "somecode", "T1")
    assert response.status_code == 401

    response = await api_client.get("protected/terminals")
    assert len(response.json()) == 0


@requires_test_env("full")
async def test_pairing_wrong_code(api_client: AsyncClient):
    pairing_code = await get_pairing_code(api_client)

    response = await add_terminal(api_client, f'wrong{pairing_code["code"][5:]}', "T1")
    assert response.status_code == 401

    response = await api_client.get("protected/terminals")
    assert len(response.json()) == 0


@requires_test_env("full")
async def test_pairing_expired_code(api_client: AsyncClient):
    pairing_code = await get_pairing_code(api_client, deadline=1)

    sleep(1.1)

    response = await add_terminal(api_client, pairing_code, "T1")
    assert response.status_code == 401

    response = await api_client.get("protected/terminals")
    assert len(response.json()) == 0


@requires_test_env("full")
async def test_authorization_missing_header(api_client: AsyncClient):
    response = await api_client.get("internal/authenticate_terminal")
    assert response.status_code == 401


@requires_test_env("full")
async def test_authorization_wrong_header_prefix(api_client: AsyncClient):
    response = await api_client.get(
        "internal/authenticate_terminal", headers={"Authorization": "Beerer foobar"}
    )
    assert response.status_code == 401


@requires_test_env("full")
async def test_authorization_invalid_token(api_client: AsyncClient):
    response = await pair_new_terminal(api_client)
    token = response.cookies["authorization"]
    invalid_token = token[:-1]
    api_client.cookies = {"authorization": invalid_token}
    response = await api_client.get("internal/authenticate_terminal")
    assert response.status_code == 401


@requires_test_env("full")
async def test_authorization_deleted_terminal(api_client: AsyncClient):
    t_name = "T1"
    await pair_new_terminal(api_client, t_name)

    response = await api_client.get("internal/authenticate_terminal")
    assert response.status_code == status.HTTP_200_OK

    response = await api_client.get(f"protected/terminals/name/{t_name}")
    assert response.status_code == 200
    t_id = response.json()["id"]
    await _delete_terminal(api_client, t_id)

    response = await api_client.get("internal/authenticate_terminal")
    assert response.status_code == 401


@requires_test_env("full")
async def test_last_connection(api_client: AsyncClient):
    t_name = "T1"
    await pair_new_terminal(api_client, t_name)
    last_connection_0 = Terminal(
        **(await api_client.get(f"protected/terminals/name/{t_name}")).json()
    ).last_connection

    response = await api_client.post("protected/apps/mock_app")
    response.raise_for_status()

    with terminals_table() as terminals:  # type: Table
        terminals.update(delete("last_connection"))
    last_connection_missing = Terminal(
        **(await api_client.get(f"protected/terminals/name/{t_name}")).json()
    )
    assert not last_connection_missing.last_connection

    sleep(0.1)

    assert (
        await api_client.get(
            "internal/auth",
            headers={
                "X-Forwarded-Host": "mock_app.myshard.org",
                "X-Forwarded-Uri": "/foo",
            },
        )
    ).status_code == status.HTTP_200_OK
    last_connection_1 = Terminal(
        **(await api_client.get(f"protected/terminals/name/{t_name}")).json()
    ).last_connection

    sleep(0.1)

    last_connection_2 = Terminal(
        **(await api_client.get(f"protected/terminals/name/{t_name}")).json()
    ).last_connection

    sleep(0.1)

    assert (
        await api_client.get(
            "internal/auth",
            headers={
                "X-Forwarded-Host": "mock_app.myshard.org",
                "X-Forwarded-Uri": "/foo",
            },
        )
    ).status_code == status.HTTP_200_OK
    last_connection_3 = Terminal(
        **(await api_client.get(f"protected/terminals/name/{t_name}")).json()
    ).last_connection

    assert (
        last_connection_0 < last_connection_1 == last_connection_2 < last_connection_3
    )


@requires_test_env("full")
async def test_pairing_with_profile_missing_owner(
    requests_mock, api_client: AsyncClient
):
    shard_without_owner = ShardDb.parse_obj(mock_shard.dict(exclude={"owner_name"}))
    with requests_mock_context(shard=shard_without_owner):
        t_name = "T1"
        await pair_new_terminal(api_client, t_name)

        response = await api_client.get("protected/identities/default")
        assert response.status_code == status.HTTP_200_OK
        assert response.json()["name"] == "Shard Owner"
        assert response.json()["email"] == "testowner@foobar.com"


@requires_test_env("full")
async def test_pairing_with_profile_missing_email(
    requests_mock, api_client: AsyncClient
):
    shard_without_email = ShardDb.parse_obj(mock_shard.dict(exclude={"owner_email"}))
    with requests_mock_context(shard=shard_without_email):
        t_name = "T1"
        await pair_new_terminal(api_client, t_name)

        response = await api_client.get("protected/identities/default")
        assert response.status_code == status.HTTP_200_OK
        assert response.json()["name"] == "test owner"
        assert response.json()["email"] is None
