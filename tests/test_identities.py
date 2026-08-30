from shard_core.data_model.identity import OutputIdentity
from httpx import AsyncClient


async def test_add_and_get(app_client: AsyncClient):
    second_identity = {"name": "second id", "description": "a public profile"}
    response_post = await app_client.put("protected/identities", json=second_identity)
    assert response_post.status_code == 201
    response = await app_client.get("protected/identities")
    assert response.status_code == 200
    result = response.json()
    assert len(result) == 2
    result_i = OutputIdentity(**(result[1]))
    assert result_i.name == second_identity["name"]
    assert result_i.description == second_identity["description"]


async def test_get_default(app_client: AsyncClient):
    i_by_list = await app_client.get("protected/identities")
    i_by_list.raise_for_status()
    i_by_default = await app_client.get("protected/identities/default")
    i_by_default.raise_for_status()
    default_identity = i_by_default.json()
    i_by_name = await app_client.get(f'protected/identities/{default_identity["id"]}')
    i_by_name.raise_for_status()
    assert i_by_list.json()[0] == i_by_default.json() == i_by_name.json()


async def test_add_another(app_client: AsyncClient):
    response = await app_client.put(
        "protected/identities", json={"name": "I2", "description": "a second identity"}
    )
    assert response.status_code == 201

    response = await app_client.get("protected/identities")
    assert len(response.json()) == 2


async def test_update(app_client: AsyncClient):
    response = await app_client.get("protected/identities/default")
    response.raise_for_status()
    default_identity = response.json()

    response = await app_client.put(
        "protected/identities",
        json={
            "id": default_identity["id"],
            "description": "an updated description",
        },
    )
    assert response.status_code == 201

    response = await app_client.get("protected/identities")
    assert len(response.json()) == 1
    assert response.json()[0]["description"] == "an updated description"
    assert response.json()[0]["name"] == "Shard Owner"


async def test_make_default(app_client: AsyncClient):
    response = await app_client.get("protected/identities/default")
    response.raise_for_status()
    first_identity = response.json()

    second_identity = {"name": "second id"}
    response = await app_client.put("protected/identities", json=second_identity)
    response.raise_for_status()
    second_identity = response.json()

    response = await app_client.post(
        f'protected/identities/{second_identity["id"]}/make-default'
    )
    response.raise_for_status()

    response = await app_client.get(f'protected/identities/{second_identity["id"]}')
    assert response.json()["is_default"] is True
    response = await app_client.get(f'protected/identities/{first_identity["id"]}')
    assert response.json()["is_default"] is False
    response = await app_client.get("protected/identities/default")
    assert response.json()["id"] == second_identity["id"]


async def test_identities_carry_no_address(app_client: AsyncClient):
    """An identity is the shard's public profile, published unauthenticated by
    /public/meta/whoareyou — a personal address has no business there."""
    response = await app_client.get("protected/identities/default")
    response.raise_for_status()
    default_identity = response.json()
    assert "email" not in default_identity

    response = await app_client.put(
        "protected/identities",
        json={"id": default_identity["id"], "email": "hello@freeshard.net"},
    )
    assert response.status_code == 201

    response = await app_client.get("public/meta/whoareyou")
    assert "email" not in response.json()
