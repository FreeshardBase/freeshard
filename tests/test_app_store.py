import pytest

from portal_core.service import app_store

pytestmark = pytest.mark.usefixtures('api_client')


def test_install():
	app_store.refresh_app_store(ref='develop')

	element_app_details = next(a for a in (app_store.get_store_apps()) if a.name == 'element')
	assert not element_app_details.is_installed

	app_store.install_store_app('element')

	element_app_details = next(a for a in (app_store.get_store_apps()) if a.name == 'element')
	assert element_app_details.is_installed
