import contextlib
import subprocess
from pathlib import Path

import gconf

from portal_core.model.terminal import InputTerminal, Icon

WAITING_DOCKER_IMAGE = 'nginx:alpine'


def get_pairing_code(api_client, deadline=None):
	response = api_client.get('protected/terminals/pairing-code', params={'deadline': deadline})
	assert response.status_code == 201
	return response.json()


def add_terminal(api_client, pairing_code, t_name):
	return api_client.post(
		f'public/pair/terminal?code={pairing_code}',
		json={'name': t_name})


@contextlib.contextmanager
def create_apps_from_docker_compose():
	dc = Path(gconf.get('path.core')) / 'docker-compose-apps.yml'
	subprocess.run(
		f'docker-compose -p apps -f {dc.name} up --remove-orphans --no-start',
		cwd=dc.parent,
		shell=True,
		check=True,
	)
	try:
		yield
	finally:
		subprocess.run(
			f'docker-compose -p apps -f {dc.name} down', cwd=dc.parent,
			shell=True,
			check=True,
		)
