from pathlib import Path

import gconf
import requests
from jinja2 import Template

from portal_core.model import InstalledApp
from portal_core.database import apps_table


def refresh_docker_compose():
	with apps_table() as apps:
		apps = [InstalledApp(**a) for a in apps.all()]

	for app in apps:
		app_data_dir = Path(gconf.get('apps.app_data_dir')) / app.name
		for data_dir in app.data_dirs or []:
			dir_ = (app_data_dir / str(data_dir).strip('/ '))
			dir_.mkdir(exist_ok=True, parents=True)

	docker_compose_filename = gconf.get('docker_compose.compose_filename')
	write_docker_compose(apps, docker_compose_filename)


def root_path():
	return Path(__file__).parent.parent


def write_docker_compose(apps, output_path: Path):
	ih_host = gconf.get('services.identity_handler.host')
	portal = requests.get(f'http://{ih_host}/public/meta/whoareyou').json()

	template_path = root_path() / 'data' / 'docker-compose.template.yml'
	template = Template(template_path.read_text())
	render_pass_one = template.render(apps=apps, portal=portal)
	render_pass_two = Template(render_pass_one).render(portal=portal)
	with open(output_path, 'w') as f:
		f.write('# == DO NOT MODIFY ==\n# this file is auto-generated\n\n')
		f.write(remove_empty_lines(render_pass_two))


def remove_empty_lines(in_: str):
	lines = in_.split('\n')
	filled_lines = [line for line in lines if line.strip() != '']
	return '\n'.join(filled_lines)
