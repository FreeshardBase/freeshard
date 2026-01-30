import logging

from shard_core.db import identities
from shard_core.data_model.identity import Identity
from shard_core.service.portal_controller import refresh_profile
from shard_core.util.signals import async_on_first_terminal_add

log = logging.getLogger(__name__)


def init_default_identity():
    if identities.count() == 0:
        default_identity = Identity.create(
            "Shard Owner",
            '"Noone wants to manage their own server"\n\nOld outdated saying',
        )
        default_identity.is_default = True
        identities.insert(default_identity.dict())
        log.info(f"created initial default identity {default_identity.id}")
    else:
        default_identity_data = identities.get_default()
        default_identity = Identity(**default_identity_data)
    return default_identity


def make_default(id):
    last_default_data = identities.get_default()
    last_default = Identity(**last_default_data)
    
    new_default_data = identities.get_by_id(id)
    if new_default_data:
        identities.update(last_default.id, is_default=False)
        identities.update(id, is_default=True)
        log.info(f"set as default {id}")
    else:
        raise KeyError(id)


def get_default_identity() -> Identity:
    default_identity_data = identities.get_default()
    return Identity(**default_identity_data)


@async_on_first_terminal_add.connect
async def enrich_identity_from_profile(_):
    profile = await refresh_profile()
    if not profile:
        log.warning(
            "Could not enrich default identity from profile because profile could not be obtained."
        )
        return

    default_identity_data = identities.get_default()
    identities.update(
        default_identity_data['id'],
        name=profile.owner if profile.owner else None,
        email=profile.owner_email if profile.owner_email else None
    )
