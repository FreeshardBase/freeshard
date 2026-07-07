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
    # valid combinations
    Lifecycle()
    Lifecycle(always_on=True)
    Lifecycle(skip_pause=True)
    Lifecycle(idle_for_pause=5)
    Lifecycle(idle_for_stop=5)
    Lifecycle(idle_for_pause=120, idle_for_stop=7200)
    Lifecycle(skip_pause=True, idle_for_stop=1800)

    # always_on excludes everything else
    with pytest.raises(ValueError):
        Lifecycle(always_on=True, skip_pause=True)
    with pytest.raises(ValueError):
        Lifecycle(always_on=True, idle_for_pause=10)
    with pytest.raises(ValueError):
        Lifecycle(always_on=True, idle_for_stop=10)

    # skip_pause excludes idle_for_pause
    with pytest.raises(ValueError):
        Lifecycle(skip_pause=True, idle_for_pause=10)

    # minimums
    with pytest.raises(ValueError):
        Lifecycle(idle_for_pause=4)
    with pytest.raises(ValueError):
        Lifecycle(idle_for_stop=4)

    # ordering when both set
    with pytest.raises(ValueError):
        Lifecycle(idle_for_pause=60, idle_for_stop=60)
    with pytest.raises(ValueError):
        Lifecycle(idle_for_pause=120, idle_for_stop=60)


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
