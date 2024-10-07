from portal_core.model.app_meta import AppMeta, Lifecycle, PortalSize
from tests.conftest import requires_test_env


@requires_test_env('full')
def test_migrate_1_0_to_1_2():
	app_meta_in = AppMeta(
		v='1.0',
		app_version='1.0.0',
		name='test',
		pretty_name='not set',
		icon='test',
		entrypoints=[],
		paths={},
		lifecycle=Lifecycle(always_on=False, idle_time_for_shutdown=60),
		minimum_portal_size=PortalSize.XS,
		store_info=None,
	)
	app_meta_in_json = app_meta_in.dict(exclude={'pretty_name'})
	app_meta_in_json['v'] = '1.0'

	app_meta_out = AppMeta.validate(app_meta_in_json)
	assert app_meta_out.v == '1.2'

	# done by migration to 1.1
	assert app_meta_out.pretty_name == 'Test'
