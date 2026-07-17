import json
import zipfile
from pathlib import Path

import pytest

from shard_core.service.app_installation.app_zip import (
    extract_app_zip,
    validate_app_zip,
)
from shard_core.service.app_installation.exceptions import InvalidAppZip
from tests.util import mock_app_store_path


def _app_meta(**overrides) -> str:
    meta = {
        "v": "1.3",
        "app_version": "0.1.0",
        "name": "some_app",
        "pretty_name": "Some App",
        "icon": "icon.svg",
        "entrypoints": [
            {
                "container_name": "some_app",
                "container_port": 80,
                "entrypoint_port": "http",
            }
        ],
        "paths": {"": {"access": "private"}},
    }
    meta.update(overrides)
    return json.dumps(meta)


def _make_zip(path: Path, members: dict[str, str]) -> Path:
    with zipfile.ZipFile(path, "w") as zip_ref:
        for name, content in members.items():
            zip_ref.writestr(name, content)
    return path


def _valid_members(prefix: str = "") -> dict[str, str]:
    return {
        f"{prefix}app_meta.json": _app_meta(),
        f"{prefix}docker-compose.yml.template": "services: {}",
        f"{prefix}icon.svg": "<svg/>",
    }


def test_validate_flat_zip(tmp_path):
    zip_file = _make_zip(tmp_path / "upload.zip", _valid_members())
    assert validate_app_zip(zip_file).name == "some_app"


def test_validate_zip_with_single_top_level_dir(tmp_path):
    zip_file = _make_zip(tmp_path / "upload.zip", _valid_members("some_app/"))
    assert validate_app_zip(zip_file).name == "some_app"


def test_validate_zip_compressed_by_macos(tmp_path):
    members = _valid_members("some_app/") | {
        "__MACOSX/some_app/._app_meta.json": "resource fork",
        "some_app/.DS_Store": "finder cruft",
    }
    zip_file = _make_zip(tmp_path / "upload.zip", members)
    assert validate_app_zip(zip_file).name == "some_app"


def test_extract_skips_archiver_cruft(tmp_path):
    members = _valid_members("some_app/") | {
        "__MACOSX/some_app/._app_meta.json": "resource fork",
        "some_app/.DS_Store": "finder cruft",
    }
    zip_file = _make_zip(tmp_path / "upload.zip", members)
    target_dir = tmp_path / "installed_apps" / "some_app"
    target_dir.mkdir(parents=True)

    extract_app_zip(zip_file, target_dir)

    assert (target_dir / "app_meta.json").exists()
    assert not (target_dir / "__MACOSX").exists()
    assert not (target_dir / ".DS_Store").exists()


def test_validate_rejects_missing_app_meta(tmp_path):
    members = _valid_members()
    del members["app_meta.json"]
    zip_file = _make_zip(tmp_path / "upload.zip", members)
    with pytest.raises(InvalidAppZip, match="app_meta.json is missing"):
        validate_app_zip(zip_file)


def test_validate_rejects_missing_compose_template(tmp_path):
    members = _valid_members()
    del members["docker-compose.yml.template"]
    zip_file = _make_zip(tmp_path / "upload.zip", members)
    with pytest.raises(InvalidAppZip, match="docker-compose.yml.template is missing"):
        validate_app_zip(zip_file)


def test_validate_rejects_app_meta_nested_deeper(tmp_path):
    zip_file = _make_zip(tmp_path / "upload.zip", _valid_members("some_app/nested/"))
    with pytest.raises(InvalidAppZip, match="app_meta.json is missing"):
        validate_app_zip(zip_file)


def test_validate_rejects_multiple_top_level_dirs(tmp_path):
    members = _valid_members("some_app/") | {"other_dir/file.txt": "x"}
    zip_file = _make_zip(tmp_path / "upload.zip", members)
    with pytest.raises(InvalidAppZip, match="app_meta.json is missing"):
        validate_app_zip(zip_file)


def test_validate_rejects_broken_app_meta(tmp_path):
    members = _valid_members() | {"app_meta.json": "{not json"}
    zip_file = _make_zip(tmp_path / "upload.zip", members)
    with pytest.raises(InvalidAppZip, match="app_meta.json is invalid"):
        validate_app_zip(zip_file)


def test_validate_rejects_app_meta_with_missing_fields(tmp_path):
    members = _valid_members() | {
        "app_meta.json": json.dumps({"v": "1.3", "name": "x"})
    }
    zip_file = _make_zip(tmp_path / "upload.zip", members)
    with pytest.raises(InvalidAppZip, match="app_meta.json is invalid"):
        validate_app_zip(zip_file)


def test_validate_rejects_non_zip(tmp_path):
    zip_file = tmp_path / "upload.zip"
    zip_file.write_bytes(b"this is not a zip file")
    with pytest.raises(InvalidAppZip, match="not a valid zip archive"):
        validate_app_zip(zip_file)


def test_validate_rejects_empty_zip(tmp_path):
    zip_file = _make_zip(tmp_path / "upload.zip", {})
    with pytest.raises(InvalidAppZip, match="empty"):
        validate_app_zip(zip_file)


@pytest.mark.parametrize("app_name", ["../evil", "foo/bar", "", "with space"])
def test_validate_rejects_unsafe_app_name(tmp_path, app_name):
    members = _valid_members() | {"app_meta.json": _app_meta(name=app_name)}
    zip_file = _make_zip(tmp_path / "upload.zip", members)
    with pytest.raises(InvalidAppZip, match="not a valid app name"):
        validate_app_zip(zip_file)


@pytest.mark.parametrize(
    "member", ["../escaped.txt", "some_app/../../escaped.txt", "/tmp/escaped.txt"]
)
def test_validate_rejects_path_traversal(tmp_path, member):
    zip_file = _make_zip(tmp_path / "upload.zip", _valid_members() | {member: "pwned"})
    with pytest.raises(InvalidAppZip, match="illegal path"):
        validate_app_zip(zip_file)


def test_extract_flat_zip(tmp_path):
    zip_file = _make_zip(tmp_path / "upload.zip", _valid_members())
    target_dir = tmp_path / "installed_apps" / "some_app"
    target_dir.mkdir(parents=True)

    extract_app_zip(zip_file, target_dir)

    assert (target_dir / "app_meta.json").exists()
    assert (target_dir / "docker-compose.yml.template").exists()
    assert (target_dir / "icon.svg").exists()


def test_extract_strips_single_top_level_dir(tmp_path):
    zip_file = _make_zip(tmp_path / "upload.zip", _valid_members("some_app/"))
    target_dir = tmp_path / "installed_apps" / "some_app"
    target_dir.mkdir(parents=True)

    extract_app_zip(zip_file, target_dir)

    assert (target_dir / "app_meta.json").exists()
    assert not (target_dir / "some_app").exists()


def test_extract_keeps_subdirectories(tmp_path):
    members = _valid_members() | {"config/settings.yml": "foo: bar"}
    zip_file = _make_zip(tmp_path / "upload.zip", members)
    target_dir = tmp_path / "installed_apps" / "some_app"
    target_dir.mkdir(parents=True)

    extract_app_zip(zip_file, target_dir)

    assert (target_dir / "config" / "settings.yml").read_text() == "foo: bar"


def test_extract_rejects_path_traversal(tmp_path):
    members = _valid_members() | {"../escaped.txt": "pwned"}
    zip_file = _make_zip(tmp_path / "upload.zip", members)
    target_dir = tmp_path / "installed_apps" / "some_app"
    target_dir.mkdir(parents=True)

    with pytest.raises(InvalidAppZip):
        extract_app_zip(zip_file, target_dir)

    assert not (tmp_path / "installed_apps" / "escaped.txt").exists()


def test_extract_mock_app_store_zip(tmp_path):
    zip_file = mock_app_store_path() / "mock_app" / "mock_app.zip"
    target_dir = tmp_path / "installed_apps" / "mock_app"
    target_dir.mkdir(parents=True)

    extract_app_zip(zip_file, target_dir)

    assert (target_dir / "app_meta.json").exists()
    assert (target_dir / "docker-compose.yml.template").exists()
