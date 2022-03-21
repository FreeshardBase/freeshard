import logging
from pathlib import Path

from setuptools import setup, find_packages

log = logging.getLogger(__name__)

setup(
	name='portal_core',
	version='0.7.0.dev0',
	packages=find_packages(),
	url='https://gitlab.com/ptl/portal_core',
	author='Max von Tettenborn',
	author_email='max.von.tettenborn@getportal.org',
	description='Core software stack that manages all aspects of a Portal',
	install_requires=[
		'gconf',
		'tinydb',
		'tinydb-serialization',
		'uvicorn',
		'fastapi',
		'pyjwt',
		'pydantic',
		'Jinja2',
		'docker',
		'python-gitlab',
		'psycopg[binary]',
		'cachetools',
		'common_py @ git+https://app_controller:MzJwN_VwwEyVmtj22LXx@gitlab.com/ptl/common_py.git',
	],
	extras_require={
		'dev': [
			'pytest',
			'pytest-docker',
		]
	},
	data_files=[
		('', ['config.yml']),
	],
	package_data={
		'portal_core': [
			*[str(f.relative_to('portal_core'))
				for f in Path('portal_core').glob('data/**/*') if f.is_file()],
		],
	}
)
