import re
from typing import Optional

from pydantic import BaseModel, Field, field_validator

# A BCP-47-ish language tag: a 2-3 letter primary subtag, optionally followed by
# region/script subtags ("en", "de", "en-us", "pt-br", "zh-hans"). The shard
# only stores this preference on behalf of the web-terminal; it is the
# web-terminal, not the shard, that decides which languages it actually offers.
# So this validates the *shape* of a language tag — enough to keep junk and
# injection out of the column — without gatekeeping the specific set, which
# would turn every new UI language into a shard migration.
_LANGUAGE_TAG_RE = re.compile(r"^[a-z]{2,3}(-[a-z0-9]{2,8})*$")
# Comfortably bounds a BCP-47-ish tag with a handful of subtags; the regex alone
# allows unboundedly many, so this is the only thing keeping the column finite.
_MAX_LANGUAGE_LENGTH = 35


def _normalize_language(value: str) -> str:
    """Lowercase and validate a language tag's shape, or raise ValueError.

    Tags are case-insensitive, so we store one canonical casing; a client that
    sends "EN" and one that sends "en" must read back the same value.
    """
    normalized = value.strip().lower()
    if not _LANGUAGE_TAG_RE.fullmatch(normalized):
        raise ValueError(f"not a valid language tag: {value!r}")
    return normalized


class OutputPreferences(BaseModel):
    """The owner's stored UI preferences.

    Deliberately an object, not a bare string: multi-user support is coming and
    this is meant to grow into a fuller per-user profile (more preferences, and
    eventually shared identity fields). A `language` of `null` means nothing has
    been stored yet, and the client falls back to its own detection — the same
    outcome an older shard produced by answering this request with a 404.
    """

    language: Optional[str] = None


class InputPreferences(BaseModel):
    """A write to the owner's UI preferences.

    `language` is required here: the only writer today is the web-terminal's
    language switcher, which always picks a concrete language. There is no
    "clear it back to auto-detect" use case to support, so the explicit version
    simply demands a language.
    """

    language: str = Field(max_length=_MAX_LANGUAGE_LENGTH)

    @field_validator("language")
    @classmethod
    def validate_language(cls, v: str) -> str:
        # Field(max_length) has already rejected an over-long raw value; this
        # only has to settle the shape and canonical casing.
        return _normalize_language(v)
