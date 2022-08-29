def test_add(api_client):
	response = api_client.put('protected/peers', json={
		'id': 'foobar',
		'name': 'p1',
		'public_bytes_b64': 'foobarba',
	})
	assert response.status_code == 201

	response = api_client.get('protected/peers')
	assert len(response.json()) == 1

	response = api_client.put('protected/peers', json={
		'id': 'foobaz',
		'name': 'p2',
		'public_bytes_b64': 'foobarba',
	})
	assert response.status_code == 201

	response = api_client.get('protected/peers')
	assert len(response.json()) == 2


def test_add_only_id(api_client):
	response = api_client.put('protected/peers', json={
		'id': 'foobar',
	})
	assert response.status_code == 201

	response = api_client.get('protected/peers')
	assert len(response.json()) == 1


def test_add_invalid_id(api_client):
	response = api_client.put('protected/peers', json={
		'id': 'foo',
	})
	assert response.status_code == 422

	response = api_client.get('protected/peers')
	assert len(response.json()) == 0


def test_update(api_client):
	response = api_client.put('protected/peers', json={
		'id': 'foobar',
		'name': 'foo',
	})
	assert response.status_code == 201

	response = api_client.get('protected/peers')
	assert len(response.json()) == 1
	assert response.json()[0]['name'] == 'foo'

	response = api_client.put('protected/peers', json={
		'id': 'foobar',
		'name': 'bar',
	})
	assert response.status_code == 201

	response = api_client.get('protected/peers')
	assert len(response.json()) == 1
	assert response.json()[0]['name'] == 'bar'
