from common_py.util import retry
from starlette import status

from portal_core.model.peer import Peer


def test_call_peer_app(peer_mock_httpx, api_client):
	path = 'foo'
	response = api_client.get(f'internal/call_peer/{peer_mock_httpx.identity.short_id}/{path}')
	assert peer_mock_httpx.route_myapp_foo_bar.called
