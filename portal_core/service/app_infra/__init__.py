from pathlib import Path

import gconf
import pydantic
import yaml
from tinydb import Query

from portal_core.database.database import apps_table, identities_table
from portal_core.model.app_meta import InstalledApp
from portal_core.model.identity import Identity, SafeIdentity
from .traefik_dyn_spec import traefik_dyn_spec


def refresh_app_infra():
	# todo: this stuff should be done in the installation call
	with apps_table() as apps:
		apps = [InstalledApp(**a) for a in apps.all()]

	with identities_table() as identities:
		default_identity = Identity(**identities.get(Query().is_default == True))  # noqa: E712
	portal = SafeIdentity(**default_identity.dict())

	traefik_dyn_filename = Path(gconf.get('path_root')) / 'core' / 'traefik_dyn' / 'traefik_dyn.yml'
	write_to_yaml(traefik_dyn_spec(apps, portal), traefik_dyn_filename)


def write_to_yaml(spec: pydantic.BaseModel, output_path: Path):
	output_path.parent.mkdir(exist_ok=True, parents=True)
	with open(output_path, 'w') as f:
		f.write('# == DO NOT MODIFY ==\n# this file is auto-generated\n\n')
		f.write(yaml.dump(spec.dict(exclude_none=True)))
