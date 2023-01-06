from datetime import datetime, timedelta
from time import sleep

from starlette import status
from tinydb.operations import delete
from tinydb.table import Table

from portal_core.database.database import apps_table, terminals_table
from portal_core.model.app import AppToInstall, InstallationReason
from portal_core.model.profile import Profile
from portal_core.model.terminal import Terminal, Icon
from portal_core.service import app_infra
from tests.conftest import management_api_mock_context
from tests.util import get_pairing_code, add_terminal, WAITING_DOCKER_IMAGE, create_apps_from_docker_compose, \
	pair_new_terminal


def _delete_terminal(api_client, t_id):
	return api_client.delete(f'protected/terminals/id/{t_id}')


def test_add_delete(api_client):
	t_name = 'T1'
	pair_new_terminal(api_client, t_name)

	response = api_client.get(f'protected/terminals/name/{t_name}')
	assert response.status_code == 200
	t_id = response.json()['id']

	response = _delete_terminal(api_client, t_id)
	assert response.status_code == 204

	response = api_client.get('protected/terminals')
	assert len(response.json()) == 0


def test_edit(api_client):
	t_name_1 = 'T1'
	pair_new_terminal(api_client, t_name_1)
	response = api_client.get(f'protected/terminals/name/{t_name_1}')
	assert response.status_code == 200
	response_terminal = Terminal(**response.json())
	assert response_terminal.name == t_name_1
	assert response_terminal.icon == Icon.UNKNOWN

	response_terminal.name = 'T2'
	response_terminal.icon = Icon.NOTEBOOK
	response = api_client.put(
		f'protected/terminals/id/{response_terminal.id}',
		data=response_terminal.json())
	assert response.status_code == 200
	response = api_client.get(f'protected/terminals/id/{response_terminal.id}')
	assert response.status_code == 200
	assert Terminal(**response.json()).name == response_terminal.name
	assert Terminal(**response.json()).icon == response_terminal.icon


def test_pairing_happy(api_client, management_api_mock):
	t_name = 'T1'
	pair_new_terminal(api_client, t_name)

	# was the terminal created with the correct data?
	response = api_client.get('protected/terminals/name/T1')
	assert response.status_code == 200
	assert response.json()['name'] == t_name
	terminal_id = response.json()['id']

	# can the terminal be authenticated using its jwt token?
	response = api_client.get('internal/authenticate_terminal')
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

	# has the default identity been update from the profile?
	assert len(management_api_mock.calls) == 1
	response = api_client.get('protected/identities/default')
	assert response.status_code == status.HTTP_200_OK
	assert response.json()['name'] == 'test owner'
	assert response.json()['email'] == 'testowner@foobar.com'


def test_pairing_two(api_client):
	t1_name = 'T1'
	t2_name = 'T2'
	pair_new_terminal(api_client, t1_name)
	pair_new_terminal(api_client, t2_name)

	response = api_client.get('protected/terminals')
	assert len(response.json()) == 2


def test_pairing_two_with_same_name(api_client):
	t1_name = 'T1'
	pair_new_terminal(api_client, t1_name)
	pair_new_terminal(api_client, t1_name)

	response = api_client.get('protected/terminals')
	assert len(response.json()) == 2


def test_pairing_no_code(api_client):
	response = add_terminal(api_client, 'somecode', 'T1')
	assert response.status_code == 401

	response = api_client.get('protected/terminals')
	assert len(response.json()) == 0


def test_pairing_wrong_code(api_client):
	pairing_code = get_pairing_code(api_client)

	response = add_terminal(api_client, f'wrong{pairing_code["code"][5:]}', 'T1')
	assert response.status_code == 401

	response = api_client.get('protected/terminals')
	assert len(response.json()) == 0


def test_pairing_expired_code(api_client):
	pairing_code = get_pairing_code(api_client, deadline=1)

	sleep(1.1)

	response = add_terminal(api_client, pairing_code, 'T1')
	assert response.status_code == 401

	response = api_client.get('protected/terminals')
	assert len(response.json()) == 0


def test_authorization_missing_header(api_client):
	response = api_client.get('internal/authenticate_terminal')
	assert response.status_code == 401


def test_authorization_wrong_header_prefix(api_client):
	response = api_client.get('internal/authenticate_terminal', headers={'Authorization': 'Beerer foobar'})
	assert response.status_code == 401


def test_authorization_invalid_token(api_client):
	response = pair_new_terminal(api_client)
	token = response.cookies['authorization']
	invalid_token = token[:-1]
	api_client.cookies = {'authorization': invalid_token}
	response = api_client.get('internal/authenticate_terminal')
	assert response.status_code == 401


def test_authorization_deleted_terminal(api_client):
	t_name = 'T1'
	pair_new_terminal(api_client, t_name)

	response = api_client.get('internal/authenticate_terminal')
	assert response.status_code == status.HTTP_200_OK

	response = api_client.get(f'protected/terminals/name/{t_name}')
	assert response.status_code == 200
	t_id = response.json()['id']
	_delete_terminal(api_client, t_id)

	response = api_client.get('internal/authenticate_terminal')
	assert response.status_code == 401


def test_last_connection(api_client):
	t_name = 'T1'
	pair_new_terminal(api_client, t_name)
	last_connection_0 = Terminal(**api_client.get(f'protected/terminals/name/{t_name}').json()).last_connection

	with apps_table() as apps:  # type: Table
		apps.truncate()
		apps.insert(AppToInstall(**{
			'name': 'foo-app',
			'image': WAITING_DOCKER_IMAGE,
			'port': 1,
			'reason': InstallationReason.CUSTOM,
		}).dict())

	app_infra.refresh_app_infra()
	with create_apps_from_docker_compose():
		with terminals_table() as terminals:  # type: Table
			terminals.update(delete('last_connection'))
		last_connection_missing = Terminal(**api_client.get(f'protected/terminals/name/{t_name}').json())
		assert not last_connection_missing.last_connection

		sleep(0.1)
		assert api_client.get('internal/auth', headers={
			'X-Forwarded-Host': 'foo-app.myportal.org',
			'X-Forwarded-Uri': '/foo'
		}).status_code == status.HTTP_200_OK
		last_connection_1 = Terminal(**api_client.get(f'protected/terminals/name/{t_name}').json()).last_connection

		sleep(0.1)
		last_connection_2 = Terminal(**api_client.get(f'protected/terminals/name/{t_name}').json()).last_connection

		sleep(0.1)
		assert api_client.get('internal/auth', headers={
			'X-Forwarded-Host': 'foo-app.myportal.org',
			'X-Forwarded-Uri': '/foo'
		}).status_code == status.HTTP_200_OK
		last_connection_3 = Terminal(**api_client.get(f'protected/terminals/name/{t_name}').json()).last_connection

	print(last_connection_0)
	print(last_connection_1)
	print(last_connection_2)
	print(last_connection_3)
	assert last_connection_0 < last_connection_1 == last_connection_2 < last_connection_3


def test_pairing_with_profile_missing_owner(api_client):
	mock_profile = Profile(
		vm_id='portal_foobar',
		owner_email='testowner@foobar.com',
		portal_size='xs',
		time_created=datetime.now() - timedelta(days=2),
		time_assigned=datetime.now() - timedelta(days=1),
	)
	with management_api_mock_context(mock_profile):
		t_name = 'T1'
		pair_new_terminal(api_client, t_name)

		response = api_client.get('protected/identities/default')
		assert response.status_code == status.HTTP_200_OK
		assert response.json()['name'] == 'Portal Owner'
		assert response.json()['email'] == 'testowner@foobar.com'


def test_pairing_with_profile_missing_email(api_client):
	mock_profile = Profile(
		vm_id='portal_foobar',
		owner='test owner',
		portal_size='xs',
		time_created=datetime.now() - timedelta(days=2),
		time_assigned=datetime.now() - timedelta(days=1),
	)
	with management_api_mock_context(mock_profile):
		t_name = 'T1'
		pair_new_terminal(api_client, t_name)

		response = api_client.get('protected/identities/default')
		assert response.status_code == status.HTTP_200_OK
		assert response.json()['name'] == 'test owner'
		assert response.json()['email'] is None
