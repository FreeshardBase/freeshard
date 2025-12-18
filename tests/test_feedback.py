from tests.conftest import requires_test_env


@requires_test_env("full")
async def test_post_quick_feedback(requests_mock, api_client):
    feedback_text = "This is a test feedback"
    response = await api_client.post(
        "protected/feedback/quick",
        json={"text": feedback_text},
    )
    assert response.status_code == 201

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
