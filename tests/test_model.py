import pytest

from shard_core.data_model.app_meta import Lifecycle, VMSize
from shard_core.data_model.util import PropertyBaseModel
from tests.conftest import requires_test_env


@requires_test_env("full")
def test_property_base_model():
    class TestModel(PropertyBaseModel):
        normal_field: str

        class Config:
            fields = {"prop_field_excluded": {"exclude": True}}

        @property
        def prop_field_included(self):
            return self.normal_field + "prop"

        @property
        def prop_field_excluded(self):
            return "bar"

    instance = TestModel(normal_field="foo")
    instance_dict = instance.dict()
    assert "normal_field" in instance_dict
    assert "prop_field_included" in instance_dict
    assert instance_dict["prop_field_included"] == "fooprop"
    assert "prop_field_excluded" not in instance_dict


@requires_test_env("full")
def test_lifecycle():
    Lifecycle(always_on=True)
    Lifecycle(idle_time_for_shutdown=5)
    with pytest.raises(ValueError):
        Lifecycle(idle_time_for_shutdown=4)
    with pytest.raises(ValueError):
        Lifecycle()
    with pytest.raises(ValueError):
        Lifecycle(always_on=True, idle_time_for_shutdown=10)


@requires_test_env("full")
def test_vm_size():
    assert VMSize.XS < VMSize.S
    assert VMSize.S < VMSize.M
    assert VMSize.M < VMSize.L
    assert VMSize.L < VMSize.XL

    assert VMSize.L == VMSize.L
    assert VMSize.L >= VMSize.L
    assert VMSize.L <= VMSize.L
    assert VMSize.L > VMSize.S
    assert VMSize.L >= VMSize.S
