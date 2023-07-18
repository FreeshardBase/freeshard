import pytest

from portal_core.model.app_meta import Lifecycle
from portal_core.model.util import PropertyBaseModel


def test_property_base_model():
	class TestModel(PropertyBaseModel):
		normal_field: str

		class Config:
			fields = {'prop_field_excluded': {'exclude': True}}

		@property
		def prop_field_included(self):
			return self.normal_field + 'prop'

		@property
		def prop_field_excluded(self):
			return 'bar'

	instance = TestModel(normal_field='foo')
	instance_dict = instance.dict()
	assert 'normal_field' in instance_dict
	assert 'prop_field_included' in instance_dict
	assert instance_dict['prop_field_included'] == 'fooprop'
	assert 'prop_field_excluded' not in instance_dict


def test_lifecycle():
	Lifecycle(always_on=True)
	Lifecycle(idle_time_for_shutdown=5)
	with pytest.raises(ValueError):
		Lifecycle(idle_time_for_shutdown=4)
	with pytest.raises(ValueError):
		Lifecycle()
	with pytest.raises(ValueError):
		Lifecycle(always_on=True, idle_time_for_shutdown=10)
