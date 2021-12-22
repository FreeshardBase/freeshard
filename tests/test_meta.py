import pytest

pytestmark = pytest.mark.usefixtures('tempfile_db_config')


def test_get_whoareyou(api_client):
	default_identity = api_client.get('protected/identities/default').json()
	whoareyou = api_client.get('public/meta/whoareyou').json()
	assert whoareyou['status'] == 'OK'
	assert whoareyou['domain'][:6].lower() == default_identity['id'][:6].lower()
	assert whoareyou['id'] == default_identity['id']


def test_get_whoami(api_client):
	whoami = api_client.get('public/meta/whoami').json()
	assert whoami['type'] == 'anonymous'
