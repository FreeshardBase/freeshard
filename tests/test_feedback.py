import pytest
import requests
import responses

from shard_core.settings import settings


async def test_post_quick_feedback(requests_mock, app_client):
    feedback_text = "This is a test feedback"
    response = await app_client.post(
        "protected/feedback/quick",
        json={"text": feedback_text},
    )
    assert response.status_code == 201
    # Handler returns no body; a regression that returned the raw controller
    # Response (the #245 500) would serialize to a non-null payload here.
    assert response.json() is None

    # Find the backend call to /api/feedback
    backend_call = next(
        (
            call
            for call in requests_mock.calls
            if call.request.path_url == "/api/feedback"
        ),
        None,
    )
    assert backend_call is not None
    assert backend_call.request.method == "POST"
    assert backend_call.request.body
    assert feedback_text in backend_call.request.body.decode()


async def test_post_quick_feedback_surfaces_controller_error(requests_mock, app_client):
    # When the controller rejects the feedback, the shard must not pretend success:
    # the handler raises on a non-2xx controller response rather than answering 201.
    controller_url = settings().freeshard_controller.base_url
    requests_mock.replace(responses.POST, f"{controller_url}/api/feedback", status=500)

    # The ASGI test transport re-raises an unhandled handler exception instead of
    # turning it into the 500 response a real server returns, so the surfaced
    # controller failure appears here as the raised HTTPError rather than a status.
    with pytest.raises(requests.exceptions.HTTPError, match="500"):
        await app_client.post(
            "protected/feedback/quick",
            json={"text": "this should fail upstream"},
        )
