from time import sleep

import gconf
import pytest
from starlette import status

pytestmark = pytest.mark.usefixtures('tempfile_db_config')


def _get_pairing_code(api_client, deadline=None):
	response = api_client.get('protected/terminals/pairing-code', params={'deadline': deadline})
	assert response.status_code == 201
	return response.json()


def _add_terminal(api_client, pairing_code, t_name, t_description):
	return api_client.post(f'public/pair/terminal?code={pairing_code}',
		json={
			'name': t_name,
			'description': t_description,
		})


def _delete_terminal(api_client, t_id):
	return api_client.delete(f'protected/terminals/id/{t_id}')


def test_add_delete(api_client, pubsub_receiver):
	t_name = 'T1'
	pairing_code = _get_pairing_code(api_client)
	assert pubsub_receiver == ('pairing_code.new', None)
	response = _add_terminal(api_client, pairing_code['code'], t_name, 'my first terminal')
	assert response.status_code == 201
	assert pubsub_receiver.last_topic_equals('terminal.add')

	response = api_client.get(f'protected/terminals/name/{t_name}')
	assert response.status_code == 200
	t_id = response.json()['id']

	response = _delete_terminal(api_client, t_id)
	assert response.status_code == 204
	assert pubsub_receiver.last_topic_equals('terminal.delete')

	response = api_client.get('protected/terminals')
	assert len(response.json()) == 0


@pytest.mark.skip
def test_pairing_happy(api_client, pubsub_receiver):
	# get a pairing code
	pairing_code = _get_pairing_code(api_client)
	assert pubsub_receiver == ('pairing_code.new', None)

	# pair a terminal using the code
	t_name = 'T1'
	t_description = 'my first terminal'
	response = _add_terminal(api_client, pairing_code['code'], t_name, t_description)
	assert response.status_code == 201
	assert pubsub_receiver.last_topic_equals('terminal.add')

	# was the terminal created with the correct data?
	response = api_client.get('protected/terminals/name/T1')
	assert response.status_code == 200
	assert response.json()['name'] == t_name
	assert response.json()['description'] == t_description
	terminal_id = response.json()['id']

	# can the terminal be authenticated using its jwt token?
	response = api_client.get('internal/authenticate')
	assert response.status_code == status.HTTP_200_OK
	assert response.headers['X-Ptl-Client-Type'] == 'terminal'
	assert response.headers['X-Ptl-Client-Id'] == terminal_id
	assert response.headers['X-Ptl-Client-Name'] == t_name

	# does whoami return the correct values?
	response = api_client.get('public/meta/whoami')
	assert response.status_code == status.HTTP_200_OK
	assert response.json()['type'] == 'terminal'
	assert response.json()['id'] == terminal_id
	assert response.json()['name'] == t_name


def test_pairing_two(api_client, pubsub_receiver):
	t1_name = 'T1'
	t1_description = 'my first terminal'
	t2_name = 'T2'
	t2_description = 'my second terminal'

	pairing_code = _get_pairing_code(api_client)
	assert pubsub_receiver == ('pairing_code.new', None)
	response = _add_terminal(api_client, pairing_code['code'], t1_name, t1_description)
	assert response.status_code == 201
	assert pubsub_receiver.last_topic_equals('terminal.add')

	pairing_code = _get_pairing_code(api_client)
	assert pubsub_receiver == ('pairing_code.new', None)
	response = _add_terminal(api_client, pairing_code['code'], t2_name, t2_description)
	assert response.status_code == 201
	assert pubsub_receiver.last_topic_equals('terminal.add')

	response = api_client.get('protected/terminals')
	assert len(response.json()) == 2


def test_pairing_no_code(api_client):
	response = _add_terminal(api_client, 'somecode', 'T1', 'my first terminal')
	assert response.status_code == 401

	response = api_client.get('protected/terminals')
	assert len(response.json()) == 0


def test_pairing_wrong_code(api_client):
	pairing_code = _get_pairing_code(api_client)

	response = _add_terminal(api_client, f'wrong{pairing_code["code"][5:]}', 'T1', 'my first terminal')
	assert response.status_code == 401

	response = api_client.get('protected/terminals')
	assert len(response.json()) == 0


def test_pairing_expired_code(api_client):
	pairing_code = _get_pairing_code(api_client, deadline=1)

	sleep(1.1)

	response = _add_terminal(api_client, pairing_code, 'T1', 'my first terminal')
	assert response.status_code == 401

	response = api_client.get('protected/terminals')
	assert len(response.json()) == 0


def test_pairing_conflict(api_client):
	t_name = 'T1'
	t_description = 'my first terminal'

	pairing_code = _get_pairing_code(api_client)
	response = _add_terminal(api_client, pairing_code['code'], t_name, t_description)
	assert response.status_code == 201

	pairing_code = _get_pairing_code(api_client)
	response = _add_terminal(api_client, pairing_code['code'], t_name, t_description)
	assert response.status_code == 409

	response = api_client.get('protected/terminals')
	assert len(response.json()) == 1


def test_authorization_missing_header(api_client):
	response = api_client.get('internal/authenticate_terminal')
	assert response.status_code == 401


def test_authorization_wrong_header_prefix(api_client):
	response = api_client.get('internal/authenticate_terminal', headers={'Authorization': 'Beerer foobar'})
	assert response.status_code == 401


@pytest.mark.skip
def test_authorization_invalid_token(api_client):
	pairing_code = _get_pairing_code(api_client)
	response = _add_terminal(api_client, pairing_code['code'], 'T1', 'my first terminal')
	assert response.status_code == 201
	token = response.cookies['authorization']
	invalid_token = token[:-1]
	response = api_client.get('internal/authenticate', cookies={'authorization': invalid_token})
	assert response.status_code == 401


@pytest.mark.skip
def test_authorization_deleted_terminal(api_client):
	t_name = 'T1'
	pairing_code = _get_pairing_code(api_client)
	response = _add_terminal(api_client, pairing_code['code'], t_name, 'my first terminal')
	assert response.status_code == 201

	response = api_client.get('internal/authenticate')
	assert response.status_code == status.HTTP_200_OK

	response = api_client.get(f'protected/terminals/name/{t_name}')
	assert response.status_code == 200
	t_id = response.json()['id']
	_delete_terminal(api_client, t_id)

	response = api_client.get('internal/authenticate')
	assert response.status_code == 401
