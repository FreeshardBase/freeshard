import json
import zipfile
from pathlib import Path

from shard_core.data_model.app_meta import AppMeta

MOCK_APP_STORE = Path(__file__).parent / "mock_app_store"


def _base_app_meta_json(v: str, lifecycle: dict | None) -> dict:
    values = {
        "v": v,
        "app_version": "1.0.0",
        "name": "test",
        "icon": "test",
        "entrypoints": [],
        "paths": {},
        "minimum_portal_size": "xs",
        "store_info": None,
    }
    if lifecycle is not None:
        values["lifecycle"] = lifecycle
    return values


def test_migrate_1_0_to_current():
    app_meta_in_json = _base_app_meta_json(
        "1.0", {"always_on": False, "idle_time_for_shutdown": 60}
    )

    app_meta_out = AppMeta.model_validate(app_meta_in_json)
    assert app_meta_out.v == "1.3"

    # done by migration to 1.1
    assert app_meta_out.pretty_name == "Test"
    # done by migration to 1.3
    assert app_meta_out.lifecycle.idle_for_stop == 60
    assert app_meta_out.lifecycle.idle_for_pause is None
    assert app_meta_out.lifecycle.skip_pause is False


def test_migrate_1_2_to_1_3_idle_time_becomes_idle_for_stop():
    values = _base_app_meta_json(
        "1.2", {"always_on": False, "idle_time_for_shutdown": 3600}
    )
    values["pretty_name"] = "Test"

    app_meta = AppMeta.model_validate(values)
    assert app_meta.v == "1.3"
    assert app_meta.lifecycle.idle_for_stop == 3600
    assert app_meta.lifecycle.idle_for_pause is None


def test_migrate_1_2_to_1_3_always_on_stays_always_on():
    values = _base_app_meta_json("1.2", {"always_on": True})
    values["pretty_name"] = "Test"

    app_meta = AppMeta.model_validate(values)
    assert app_meta.v == "1.3"
    assert app_meta.lifecycle.always_on is True
    assert app_meta.lifecycle.idle_for_stop is None


def test_migrate_1_2_to_1_3_missing_lifecycle_gets_defaults():
    values = _base_app_meta_json("1.2", None)
    values["pretty_name"] = "Test"

    app_meta = AppMeta.model_validate(values)
    assert app_meta.v == "1.3"
    assert app_meta.lifecycle.always_on is False
    assert app_meta.lifecycle.skip_pause is False
    assert app_meta.lifecycle.idle_for_pause is None
    assert app_meta.lifecycle.idle_for_stop is None


def test_all_mock_app_store_metas_migrate():
    """Every app_meta.json fixture (the app-repository stand-ins) must load
    through the migration chain without regeneration."""
    zips = sorted(MOCK_APP_STORE.glob("*/*.zip"))
    assert zips, "expected mock app store zips"
    for zip_path in zips:
        with zipfile.ZipFile(zip_path) as zf:
            values = json.loads(zf.read("app_meta.json"))
        old_lifecycle = values.get("lifecycle", {})
        app_meta = AppMeta.model_validate(values)
        assert app_meta.v == "1.3", zip_path
        if old_lifecycle.get("always_on"):
            assert app_meta.lifecycle.always_on is True, zip_path
        elif "idle_time_for_shutdown" in old_lifecycle:
            assert (
                app_meta.lifecycle.idle_for_stop
                == old_lifecycle["idle_time_for_shutdown"]
            ), zip_path
