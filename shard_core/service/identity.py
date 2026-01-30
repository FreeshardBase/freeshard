import logging

from shard_core.database import db_methods
from shard_core.data_model.identity import Identity
from shard_core.service.portal_controller import refresh_profile
from shard_core.util.signals import async_on_first_terminal_add

log = logging.getLogger(__name__)


def init_default_identity():
    if db_methods.count_identities() == 0:
        default_identity = Identity.create(
            "Shard Owner",
            '"Noone wants to manage their own server"\n\nOld outdated saying',
        )
        default_identity.is_default = True
        db_methods.insert_identity(default_identity.dict())
        log.info(f"created initial default identity {default_identity.id}")
    else:
        default_identity_data = db_methods.get_default_identity()
        default_identity = Identity(**default_identity_data)
    return default_identity


def make_default(id):
    last_default_data = db_methods.get_default_identity()
    last_default = Identity(**last_default_data)
    
    new_default_data = db_methods.get_identity_by_id(id)
    if new_default_data:
        new_default = Identity(**new_default_data)
        last_default.is_default = False
        new_default.is_default = True
        db_methods.update_identity(last_default.id, last_default.dict())
        db_methods.update_identity(new_default.id, new_default.dict())
        log.info(f"set as default {new_default.id}")
    else:
        raise KeyError(id)


def get_default_identity() -> Identity:
    default_identity_data = db_methods.get_default_identity()
    return Identity(**default_identity_data)


@async_on_first_terminal_add.connect
async def enrich_identity_from_profile(_):
    profile = await refresh_profile()
    if not profile:
        log.warning(
            "Could not enrich default identity from profile because profile could not be obtained."
        )
        return

    default_identity_data = db_methods.get_default_identity()
    updates = {}
    if profile.owner:
        updates["name"] = profile.owner
    if profile.owner_email:
        updates["email"] = profile.owner_email
    
    if updates:
        db_methods.update_identity(default_identity_data['id'], updates)
