import pytest

from portal_core.model.app_meta import Lifecycle, PortalSize
from tests.conftest import requires_test_env


@requires_test_env('full')
def test_lifecycle():
	Lifecycle(always_on=True)
	Lifecycle(idle_time_for_shutdown=5)
	with pytest.raises(ValueError):
		Lifecycle(idle_time_for_shutdown=4)
	with pytest.raises(ValueError):
		Lifecycle()
	with pytest.raises(ValueError):
		Lifecycle(always_on=True, idle_time_for_shutdown=10)


@requires_test_env('full')
def test_portal_size():
	assert PortalSize.XS < PortalSize.S
	assert PortalSize.S < PortalSize.M
	assert PortalSize.M < PortalSize.L
	assert PortalSize.L < PortalSize.XL

	assert PortalSize.L == PortalSize.L
	assert PortalSize.L >= PortalSize.L
	assert PortalSize.L <= PortalSize.L
	assert PortalSize.L > PortalSize.S
	assert PortalSize.L >= PortalSize.S
