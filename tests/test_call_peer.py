def test_call_peer_app_basic(peer_mock_requests, api_client):
	path = 'foo'
	response = api_client.get(f'internal/call_peer/{peer_mock_requests.identity.short_id}/{path}')
	assert response.status_code == 200
	assert peer_mock_requests.route_myapp_foo_bar.call_count == 1
