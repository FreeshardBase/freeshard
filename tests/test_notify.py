from httpx import AsyncClient


async def test_notify_broadcasts_message_type(app_client: AsyncClient, mocker):
    mock_broadcast = mocker.patch(
        "shard_core.web.management.notify.ws_worker.broadcast_message"
    )
    response = await app_client.post(
        "management/notify",
        json={"type": "subscription_updated"},
        headers={"authorization": "constantSharedSecret"},
    )
    assert response.status_code == 204
    mock_broadcast.assert_called_once_with("subscription_updated")


async def test_notify_swallows_broadcast_errors(app_client: AsyncClient, mocker):
    mocker.patch(
        "shard_core.web.management.notify.ws_worker.broadcast_message",
        side_effect=RuntimeError("queue exploded"),
    )
    response = await app_client.post(
        "management/notify",
        json={"type": "subscription_updated"},
        headers={"authorization": "constantSharedSecret"},
    )
    assert response.status_code == 204


async def test_notify_rejects_missing_type(app_client: AsyncClient):
    response = await app_client.post(
        "management/notify",
        json={},
        headers={"authorization": "constantSharedSecret"},
    )
    assert response.status_code == 422
