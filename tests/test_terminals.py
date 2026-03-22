from time import sleep

from httpx import AsyncClient
from starlette import status
from tinydb.operations import delete

from shard_core.data_model.backend.shard_model import ShardDb
from shard_core.database.database import terminals_table
from shard_core.data_model.terminal import Terminal, Icon
from tests.conftest import requests_mock_context, mock_shard, requires_test_env
from tests.util import get_pairing_code, add_terminal, pair_new_terminal


async def _delete_terminal(app_client: AsyncClient, t_id):
    return await app_client.delete(f"protected/terminals/id/{t_id}")


async def test_add_delete(app_client: AsyncClient):
    t_name = "T1"
    await pair_new_terminal(app_client, t_name)

    response = await app_client.get(f"protected/terminals/name/{t_name}")
    assert response.status_code == 200
    t_id = response.json()["id"]

    response = await _delete_terminal(app_client, t_id)
    assert response.status_code == 204

    response = await app_client.get("protected/terminals")
    assert len(response.json()) == 0


async def test_edit(app_client: AsyncClient):
    t_name_1 = "T1"
    await pair_new_terminal(app_client, t_name_1)
    response = await app_client.get(f"protected/terminals/name/{t_name_1}")
    assert response.status_code == 200
    response_terminal = Terminal(**response.json())
    assert response_terminal.name == t_name_1
    assert response_terminal.icon == Icon.UNKNOWN

    response_terminal.name = "T2"
    response_terminal.icon = Icon.NOTEBOOK
    response = await app_client.put(
        f"protected/terminals/id/{response_terminal.id}",
        content=response_terminal.model_dump_json(),
        headers={"Content-Type": "application/json"},
    )
    assert response.status_code == 200
    response = await app_client.get(f"protected/terminals/id/{response_terminal.id}")
    assert response.status_code == 200
    assert Terminal(**response.json()).name == response_terminal.name
    assert Terminal(**response.json()).icon == response_terminal.icon


async def test_pairing_happy(requests_mock, app_client: AsyncClient):
    t_name = "T1"
    await pair_new_terminal(app_client, t_name)

    # was the terminal created with the correct data?
    response = await app_client.get("protected/terminals/name/T1")
    assert response.status_code == 200
    assert response.json()["name"] == t_name
    terminal_id = response.json()["id"]

    # can the terminal be authenticated using its jwt token?
    response = await app_client.get("internal/authenticate_terminal")
    assert response.status_code == status.HTTP_200_OK
    assert response.headers["X-Ptl-Client-Type"] == "terminal"
    assert response.headers["X-Ptl-Client-Id"] == terminal_id
    assert response.headers["X-Ptl-Client-Name"] == t_name

    # does whoami return the correct values?
    response = await app_client.get("public/meta/whoami")
    assert response.status_code == status.HTTP_200_OK
    assert response.json()["type"] == "terminal"
    assert response.json()["id"] == terminal_id
    assert response.json()["name"] == t_name

    # has the default identity been updated from the profile?
    # With app_client there is no startup call, so only 1 call (from pairing).
    assert len(requests_mock.calls) == 1
    response = await app_client.get("protected/identities/default")
    assert response.status_code == status.HTTP_200_OK
    assert response.json()["name"] == "test owner"
    assert response.json()["email"] == "testowner@foobar.com"


async def test_pairing_two(app_client: AsyncClient):
    t1_name = "T1"
    t2_name = "T2"
    await pair_new_terminal(app_client, t1_name)
    await pair_new_terminal(app_client, t2_name)

    response = await app_client.get("protected/terminals")
    assert len(response.json()) == 2


async def test_pairing_two_with_same_name(app_client: AsyncClient):
    t1_name = "T1"
    await pair_new_terminal(app_client, t1_name)
    await pair_new_terminal(app_client, t1_name)

    response = await app_client.get("protected/terminals")
    assert len(response.json()) == 2


async def test_pairing_no_code(app_client: AsyncClient):
    response = await add_terminal(app_client, "somecode", "T1")
    assert response.status_code == 401

    response = await app_client.get("protected/terminals")
    assert len(response.json()) == 0


async def test_pairing_wrong_code(app_client: AsyncClient):
    pairing_code = await get_pairing_code(app_client)

    response = await add_terminal(app_client, f'wrong{pairing_code["code"][5:]}', "T1")
    assert response.status_code == 401

    response = await app_client.get("protected/terminals")
    assert len(response.json()) == 0


async def test_pairing_expired_code(app_client: AsyncClient):
    pairing_code = await get_pairing_code(app_client, deadline=1)

    sleep(1.1)

    response = await add_terminal(app_client, pairing_code, "T1")
    assert response.status_code == 401

    response = await app_client.get("protected/terminals")
    assert len(response.json()) == 0


async def test_authorization_missing_header(app_client: AsyncClient):
    response = await app_client.get("internal/authenticate_terminal")
    assert response.status_code == 401


async def test_authorization_wrong_header_prefix(app_client: AsyncClient):
    response = await app_client.get(
        "internal/authenticate_terminal", headers={"Authorization": "Beerer foobar"}
    )
    assert response.status_code == 401


async def test_authorization_invalid_token(app_client: AsyncClient):
    response = await pair_new_terminal(app_client)
    token = response.cookies["authorization"]
    invalid_token = token[:-1]
    app_client.cookies = {"authorization": invalid_token}
    response = await app_client.get("internal/authenticate_terminal")
    assert response.status_code == 401


async def test_authorization_deleted_terminal(app_client: AsyncClient):
    t_name = "T1"
    await pair_new_terminal(app_client, t_name)

    response = await app_client.get("internal/authenticate_terminal")
    assert response.status_code == status.HTTP_200_OK

    response = await app_client.get(f"protected/terminals/name/{t_name}")
    assert response.status_code == 200
    t_id = response.json()["id"]
    await _delete_terminal(app_client, t_id)

    response = await app_client.get("internal/authenticate_terminal")
    assert response.status_code == 401


async def test_pairing_with_profile_missing_owner(
    requests_mock, app_client: AsyncClient
):
    shard_without_owner = ShardDb.model_validate(
        mock_shard.model_dump(exclude={"owner_name"})
    )
    with requests_mock_context(shard=shard_without_owner):
        t_name = "T1"
        await pair_new_terminal(app_client, t_name)

        response = await app_client.get("protected/identities/default")
        assert response.status_code == status.HTTP_200_OK
        assert response.json()["name"] == "Shard Owner"
        assert response.json()["email"] == "testowner@foobar.com"


async def test_pairing_with_profile_missing_email(
    requests_mock, app_client: AsyncClient
):
    shard_without_email = ShardDb.model_validate(
        mock_shard.model_dump(exclude={"owner_email"})
    )
    with requests_mock_context(shard=shard_without_email):
        t_name = "T1"
        await pair_new_terminal(app_client, t_name)

        response = await app_client.get("protected/identities/default")
        assert response.status_code == status.HTTP_200_OK
        assert response.json()["name"] == "test owner"
        assert response.json()["email"] is None


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
