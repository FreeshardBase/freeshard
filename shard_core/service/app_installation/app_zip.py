import json
import logging
import re
import shutil
import zipfile
from pathlib import Path

from shard_core.data_model.app_meta import AppMeta
from .exceptions import InvalidAppZip

log = logging.getLogger(__name__)

REQUIRED_FILES = ("app_meta.json", "docker-compose.yml.template")
APP_NAME_PATTERN = re.compile(r"[a-zA-Z0-9][a-zA-Z0-9_-]{0,63}")


def validate_app_zip(zip_file: Path) -> AppMeta:
    """Read the app metadata from an archive, rejecting anything unfit to install."""
    try:
        with zipfile.ZipFile(zip_file, "r") as zip_ref:
            names = _member_names(zip_ref)
            root = _find_root(names)
            for required in REQUIRED_FILES:
                if root + required not in names:
                    raise InvalidAppZip(f"{required} is missing from the archive")
            app_meta = _parse_app_meta(zip_ref.read(root + "app_meta.json"))
    except zipfile.BadZipFile as e:
        raise InvalidAppZip(f"not a valid zip archive: {e}")

    if not APP_NAME_PATTERN.fullmatch(app_meta.name):
        raise InvalidAppZip(
            f"app name {app_meta.name!r} in app_meta.json is not a valid app name"
        )
    return app_meta


def extract_app_zip(zip_file: Path, target_dir: Path):
    """Extract an app archive, stripping a single top-level directory if present."""
    target_root = target_dir.resolve()
    with zipfile.ZipFile(zip_file, "r") as zip_ref:
        names = _member_names(zip_ref)
        root = _find_root(names)
        for name in names:
            relative = name[len(root) :]
            target = (target_dir / relative).resolve()
            if not relative or target_root not in target.parents:
                raise InvalidAppZip(f"archive member {name!r} has an illegal path")
            target.parent.mkdir(parents=True, exist_ok=True)
            with zip_ref.open(name) as source, open(target, "wb") as f:
                shutil.copyfileobj(source, f)


def _member_names(zip_ref: zipfile.ZipFile) -> list[str]:
    names = [
        i.filename
        for i in zip_ref.infolist()
        if not i.is_dir() and not _is_archiver_cruft(i.filename)
    ]
    if not names:
        raise InvalidAppZip("the archive is empty")
    for name in names:
        parts = Path(name).parts
        if name.startswith("/") or ".." in parts or Path(name).is_absolute():
            raise InvalidAppZip(f"archive member {name!r} has an illegal path")
    return names


def _is_archiver_cruft(name: str) -> bool:
    # macOS "Compress" adds these next to the compressed folder — without ignoring
    # them, such an archive looks like it has two top-level directories
    return name.startswith("__MACOSX/") or Path(name).name == ".DS_Store"


def _find_root(names: list[str]) -> str:
    """Return the prefix the app files live under: "" or "<single top-level dir>/"."""
    if "app_meta.json" in names:
        return ""
    top_level = {name.split("/", 1)[0] for name in names}
    if len(top_level) == 1:
        root = top_level.pop() + "/"
        if root + "app_meta.json" in names:
            return root
    raise InvalidAppZip(
        "app_meta.json is missing from the archive root; the app files must be at "
        "the top level of the zip, or inside a single directory"
    )


def _parse_app_meta(raw: bytes) -> AppMeta:
    try:
        return AppMeta.model_validate(json.loads(raw))
    except Exception as e:
        raise InvalidAppZip(f"app_meta.json is invalid: {e}")
