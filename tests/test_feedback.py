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
    # The handler must NOT return the raw requests.Response it gets back from the
    # controller: FastAPI cannot JSON-encode a live streamed Response, which is the
    # 500 this test guards against (issue #245). A clean handler returns no body, so
    # the decoded payload is null. A regression that returns the Response instead
    # serializes it to a (non-null) dict under this test's mock, tripping this
    # assertion. (The mock yields an encodable fake Response, so it can't reproduce
    # the production 500 itself -- it catches the regression by its body, not status.)
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
    # turning it into the 500 response a real server returns, so a surfaced
    # controller failure appears here as the raised HTTPError. Either way the shard
    # does not answer 201 — drop the raise_for_status and this stops raising.
    with pytest.raises(requests.exceptions.HTTPError, match="500"):
        await app_client.post(
            "protected/feedback/quick",
            json={"text": "this should fail upstream"},
        )
