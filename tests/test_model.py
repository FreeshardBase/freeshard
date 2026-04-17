import pytest
from pydantic import BaseModel, computed_field

from shard_core.data_model.app_meta import Lifecycle, VMSize


def test_computed_field_model():
    class TestModel(BaseModel):
        normal_field: str

        @computed_field
        @property
        def prop_field_included(self) -> str:
            return self.normal_field + "prop"

    instance = TestModel(normal_field="foo")
    instance_dict = instance.model_dump()
    assert "normal_field" in instance_dict
    assert "prop_field_included" in instance_dict
    assert instance_dict["prop_field_included"] == "fooprop"


def test_lifecycle():
    Lifecycle(always_on=True)
    Lifecycle(idle_time_for_shutdown=5)
    with pytest.raises(ValueError):
        Lifecycle(idle_time_for_shutdown=4)
    with pytest.raises(ValueError):
        Lifecycle()
    with pytest.raises(ValueError):
        Lifecycle(always_on=True, idle_time_for_shutdown=10)


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
