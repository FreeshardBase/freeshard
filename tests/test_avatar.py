from pathlib import Path

from fastapi import status
from httpx import AsyncClient

from shard_core.data_model.identity import OutputIdentity
from shard_core.settings import settings


async def test_upload_happy(app_client: AsyncClient):
    i = await app_client.get("protected/identities/default")
    default_id = OutputIdentity.model_validate(i.json())
    with open("tests/mock_assets/mock_avatar.png", "rb") as avatar_file:
        response = await app_client.put(
            f"protected/identities/{default_id.id}/avatar", files={"file": avatar_file}
        )
    response.raise_for_status()

    uploaded_file_path = (
        Path(settings().path_root)
        / "core"
        / "assets"
        / "avatars"
        / f"{default_id.id}.png"
    )
    assert uploaded_file_path.exists()
    with open("tests/mock_assets/mock_avatar.png", "rb") as avatar_file:
        assert uploaded_file_path.read_bytes() == avatar_file.read()


async def test_upload_wrong_file_type(app_client: AsyncClient):
    i = await app_client.get("protected/identities/default")
    default_id = OutputIdentity.model_validate(i.json())
    response = await app_client.put(
        f"protected/identities/{default_id.id}/avatar",
        files={"file": ("filename.pdf", b"some bytes")},
    )
    assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY


async def test_upload_to_unknown_identity(app_client: AsyncClient):
    i = await app_client.get("protected/identities/default")
    default_id = OutputIdentity.model_validate(i.json())
    wrong_hash_id = "foobar" + default_id.id[6:]
    response = await app_client.put(
        f"protected/identities/{wrong_hash_id}/avatar",
        files={"file": ("filename.png", b"some bytes")},
    )
    assert response.status_code == status.HTTP_404_NOT_FOUND


async def test_upload_different_filetypes(app_client: AsyncClient):
    i = await app_client.get("protected/identities/default")
    default_id = OutputIdentity.model_validate(i.json())

    response = await app_client.put(
        f"protected/identities/{default_id.id}/avatar",
        files={"file": ("filename.png", b"some bytes")},
    )
    response.raise_for_status()

    response = await app_client.put(
        f"protected/identities/{default_id.id}/avatar",
        files={"file": ("filename.jpg", b"some bytes")},
    )
    response.raise_for_status()

    avatars_dir = Path(settings().path_root) / "core" / "assets" / "avatars"
    assert len(list(avatars_dir.iterdir())) == 1


async def test_put_and_get_happy(app_client: AsyncClient):
    i = await app_client.get("protected/identities/default")
    default_id = OutputIdentity.model_validate(i.json())

    sent_bytes = b"some bytes"
    response = await app_client.put(
        f"protected/identities/{default_id.id}/avatar",
        files={"file": ("filename.png", sent_bytes)},
    )
    response.raise_for_status()

    response = await app_client.get(f"protected/identities/{default_id.id}/avatar")
    response.raise_for_status()
    response_bytes = response.read()
    assert response_bytes == sent_bytes
    assert response.headers["content-type"] == "image/png"

    response = await app_client.get("public/meta/avatar")
    response.raise_for_status()
    response_bytes = response.read()
    assert response_bytes == sent_bytes
    assert response.headers["content-type"] == "image/png"


async def test_get_from_missing_identity(app_client: AsyncClient):
    i = await app_client.get("protected/identities/default")
    default_id = OutputIdentity.model_validate(i.json())
    wrong_hash_id = "foobar" + default_id.id[6:]

    response = await app_client.get(f"protected/identities/{wrong_hash_id}/avatar")
    assert response.status_code == status.HTTP_404_NOT_FOUND


async def test_get_missing_avatar(app_client: AsyncClient):
    i = await app_client.get("protected/identities/default")
    default_id = OutputIdentity.model_validate(i.json())

    response = await app_client.get(f"protected/identities/{default_id.id}/avatar")
    assert response.status_code == status.HTTP_404_NOT_FOUND


async def test_delete_avatar_happy(app_client: AsyncClient):
    i = await app_client.get("protected/identities/default")
    default_id = OutputIdentity.model_validate(i.json())

    sent_bytes = b"some bytes"
    response = await app_client.put(
        f"protected/identities/{default_id.id}/avatar",
        files={"file": ("filename.png", sent_bytes)},
    )
    response.raise_for_status()

    response = await app_client.delete(f"protected/identities/{default_id.id}/avatar")
    response.raise_for_status()

    response = await app_client.get(f"protected/identities/{default_id.id}/avatar")
    assert response.status_code == status.HTTP_404_NOT_FOUND


async def test_delete_from_missing_identity(app_client: AsyncClient):
    i = await app_client.get("protected/identities/default")
    default_id = OutputIdentity.model_validate(i.json())
    wrong_hash_id = "foobar" + default_id.id[6:]

    response = await app_client.delete(f"protected/identities/{wrong_hash_id}/avatar")
    assert response.status_code == status.HTTP_404_NOT_FOUND


async def test_delete_missing_avatar(app_client: AsyncClient):
    i = await app_client.get("protected/identities/default")
    default_id = OutputIdentity.model_validate(i.json())

    response = await app_client.delete(f"protected/identities/{default_id.id}/avatar")
    response.raise_for_status()


async def test_put_and_get_default_avatar_happy(app_client: AsyncClient):
    sent_bytes = b"some bytes"
    response = await app_client.put(
        "protected/identities/default/avatar",
        files={"file": ("filename.png", sent_bytes)},
    )
    response.raise_for_status()

    response = await app_client.get("protected/identities/default/avatar")
    response.raise_for_status()

    response_bytes = response.read()
    assert response_bytes == sent_bytes
    assert response.headers["content-type"] == "image/png"


async def test_get_missing_default_avatar(app_client: AsyncClient):
    response = await app_client.get("protected/identities/default/avatar")
    assert response.status_code == status.HTTP_404_NOT_FOUND


async def test_delete_default_avatar(app_client: AsyncClient):
    sent_bytes = b"some bytes"
    response = await app_client.put(
        "protected/identities/default/avatar",
        files={"file": ("filename.png", sent_bytes)},
    )
    response.raise_for_status()

    response = await app_client.delete("protected/identities/default/avatar")
    response.raise_for_status()

    response = await app_client.get("protected/identities/default/avatar")
    assert response.status_code == status.HTTP_404_NOT_FOUND
