"""The owner's UI preferences endpoint.

What is under test is the contract the web-terminal relies on: a session reads
its stored language on load and writes it from the settings switcher, an unset
language reads back as null (so the client falls back to its own detection just
as it does against an older shard's 404), and a written value survives a reload
by actually landing in Postgres.
"""

from httpx import AsyncClient

from shard_core.database import users as db_users
from shard_core.database.connection import db_conn
from tests.util import pair_new_terminal

PREFERENCES = "protected/preferences"


async def get_owner():
    async with db_conn() as conn:
        return await db_users.get_owner(conn)


# --- authentication --------------------------------------------------------------


async def test_without_a_session_is_rejected(app_client: AsyncClient):
    """No cookie means forwardAuth would never have let this through; the
    endpoint resolves no user and refuses rather than inventing one."""
    assert (await app_client.get(PREFERENCES)).status_code == 401
    assert (
        await app_client.put(PREFERENCES, json={"language": "de"})
    ).status_code == 401


# --- reading --------------------------------------------------------------------


async def test_fresh_session_has_no_language(app_client: AsyncClient):
    await pair_new_terminal(app_client)

    response = await app_client.get(PREFERENCES)

    assert response.status_code == 200
    # an object, never a bare string, and null means "nothing stored yet"
    assert response.json() == {"language": None}


async def test_reads_back_a_stored_language(app_client: AsyncClient):
    await pair_new_terminal(app_client)
    await app_client.put(PREFERENCES, json={"language": "de"})

    body = (await app_client.get(PREFERENCES)).json()

    assert body == {"language": "de"}


# --- writing --------------------------------------------------------------------


async def test_put_persists_the_language(app_client: AsyncClient):
    await pair_new_terminal(app_client)

    response = await app_client.put(PREFERENCES, json={"language": "de"})

    assert response.status_code == 200
    assert response.json() == {"language": "de"}
    # it is not enough that the response echoes it: a reload reads the DB, so
    # the value has to be on the row, not just in the reply
    assert (await get_owner()).language == "de"


async def test_put_overwrites_a_previous_language(app_client: AsyncClient):
    await pair_new_terminal(app_client)
    await app_client.put(PREFERENCES, json={"language": "de"})

    response = await app_client.put(PREFERENCES, json={"language": "en"})

    assert response.json() == {"language": "en"}
    assert (await get_owner()).language == "en"


async def test_put_normalizes_case(app_client: AsyncClient):
    """Tags are case-insensitive; a client sending "DE" and one sending "de"
    must read back the same value, or language detection would miss a match."""
    await pair_new_terminal(app_client)

    response = await app_client.put(PREFERENCES, json={"language": "DE"})

    assert response.json() == {"language": "de"}
    assert (await get_owner()).language == "de"


async def test_put_trims_surrounding_whitespace(app_client: AsyncClient):
    """A padded tag is the same preference as the trimmed one; store the
    trimmed form so a later read matches an unpadded detection."""
    await pair_new_terminal(app_client)

    response = await app_client.put(PREFERENCES, json={"language": " de "})

    assert response.json() == {"language": "de"}
    assert (await get_owner()).language == "de"


async def test_put_accepts_a_region_subtag(app_client: AsyncClient):
    """The shard is not the authority on which languages the web-terminal
    offers, so a well-formed tag it does not itself enumerate is still stored."""
    await pair_new_terminal(app_client)

    response = await app_client.put(PREFERENCES, json={"language": "pt-BR"})

    assert response.status_code == 200
    assert response.json() == {"language": "pt-br"}


# --- rejecting bad input --------------------------------------------------------


async def test_put_rejects_non_language_text(app_client: AsyncClient):
    """Free text is not a language tag; the column must stay a language tag so a
    later reader can trust its shape."""
    await pair_new_terminal(app_client)

    response = await app_client.put(PREFERENCES, json={"language": "english please"})

    assert response.status_code == 422
    assert (await get_owner()).language is None


async def test_put_rejects_an_empty_language(app_client: AsyncClient):
    await pair_new_terminal(app_client)

    response = await app_client.put(PREFERENCES, json={"language": ""})

    assert response.status_code == 422


# A tag that is well-formed (so the shape regex passes) but over the length cap:
# the regex alone allows arbitrarily many subtags, so the cap is the only thing
# keeping an unbounded tag out of the column. These must exercise the cap, not
# the regex — hence valid-shape strings on both sides of the 35-char boundary.
_VALID_TAG_AT_LIMIT = "en-aaaaaaaa-aaaaaaaa-aaaaaaaa-aaaaa"  # 35 chars
_VALID_TAG_OVER_LIMIT = "en-aaaaaaaa-aaaaaaaa-aaaaaaaa-aaaaaa"  # 36 chars


async def test_put_accepts_a_tag_at_the_length_limit(app_client: AsyncClient):
    await pair_new_terminal(app_client)

    response = await app_client.put(
        PREFERENCES, json={"language": _VALID_TAG_AT_LIMIT}
    )

    assert response.status_code == 200
    assert response.json() == {"language": _VALID_TAG_AT_LIMIT}


async def test_put_rejects_a_well_formed_but_overlong_language(app_client: AsyncClient):
    """One char past the limit, still a valid shape, must be refused — otherwise
    the regex's unbounded subtag repetition would write an arbitrarily long tag
    straight to the TEXT column."""
    await pair_new_terminal(app_client)

    response = await app_client.put(
        PREFERENCES, json={"language": _VALID_TAG_OVER_LIMIT}
    )

    assert response.status_code == 422
    assert (await get_owner()).language is None


async def test_put_requires_the_language_field(app_client: AsyncClient):
    """language is required: the only writer, the switcher, always picks one, so
    there is no partial-write path to get wrong."""
    await pair_new_terminal(app_client)

    response = await app_client.put(PREFERENCES, json={})

    assert response.status_code == 422


async def test_put_rejects_an_explicit_null_language(app_client: AsyncClient):
    """Distinct from the absent case: a present-but-null language must 422 too,
    so the field cannot quietly become clearable without a deliberate change."""
    await pair_new_terminal(app_client)

    response = await app_client.put(PREFERENCES, json={"language": None})

    assert response.status_code == 422
