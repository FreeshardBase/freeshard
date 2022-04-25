def test_add(api_client):
	response = api_client.post('protected/peers', json={
		'id': 'foo',
		'name': 'p1',
		'public_bytes_b64': 'foobarba',
	})
	assert response.status_code == 201

	response = api_client.get('protected/peers')
	assert len(response.json()) == 1
