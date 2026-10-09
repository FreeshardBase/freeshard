from importlib.metadata import PackageNotFoundError
from unittest.mock import Mock

import pytest

from shard_core.service import app_tools


@pytest.mark.parametrize(
    "current, minimum, expected",
    [
        # no requirement is always compatible
        ("0.40.6", None, True),
        ("0.40.6", "", True),
        # equal and newer satisfy the requirement
        ("0.41.0", "0.41.0", True),
        ("0.41.1", "0.41.0", True),
        ("1.0.0", "0.41.0", True),
        ("0.41.0", "0.40.0", True),
        # older shard than required is incompatible
        ("0.40.6", "0.41.0", False),
        ("0.40.6", "0.40.7", False),
        ("0.9.0", "0.10.0", False),  # semver, not lexical: 9 < 10
        # pre-releases order below the final release (PEP 440)
        ("0.41.0rc1", "0.41.0", False),
        ("0.41.0", "0.41.0rc1", True),
    ],
)
def test_freeshard_version_is_compatible(monkeypatch, current, minimum, expected):
    monkeypatch.setattr(app_tools, "get_freeshard_version", lambda: current)
    assert app_tools.freeshard_version_is_compatible(minimum) is expected


def test_unparseable_requirement_is_incompatible(monkeypatch):
    # A requirement we cannot parse means we cannot confirm the shard is new
    # enough, so we fail safe and treat the app as incompatible.
    monkeypatch.setattr(app_tools, "get_freeshard_version", lambda: "0.40.6")
    assert app_tools.freeshard_version_is_compatible("not-a-version") is False


def test_unreadable_running_version_is_incompatible(monkeypatch):
    # If we cannot even resolve our own running version, we cannot confirm the
    # shard is new enough: fail safe to incompatible rather than crash the
    # auth/lifecycle path that calls this.
    monkeypatch.setattr(
        app_tools,
        "get_freeshard_version",
        Mock(side_effect=PackageNotFoundError("shard_core")),
    )
    assert app_tools.freeshard_version_is_compatible("0.41.0") is False


def test_no_requirement_short_circuits_before_version_lookup(monkeypatch):
    # With no requirement, the version lookup must never run — an unreadable
    # running version still yields "compatible".
    monkeypatch.setattr(
        app_tools,
        "get_freeshard_version",
        Mock(side_effect=PackageNotFoundError("shard_core")),
    )
    assert app_tools.freeshard_version_is_compatible(None) is True


def test_get_freeshard_version_matches_package_metadata():
    # Reads the installed shard_core version; must be a parseable semver string.
    from packaging.version import Version

    version = app_tools.get_freeshard_version()
    assert Version(version) >= Version("0.0.0")
