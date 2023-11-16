import logging

from setuptools import setup, find_packages

log = logging.getLogger(__name__)

setup(
	name='portal_core',
	version='0.24.1',
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
		'websockets',
		'pyjwt',
		'pydantic==1.*',
		'Jinja2',
		'pyyaml',
		'docker',
		'python-gitlab',
		'psycopg[binary]',
		'cachetools',
		'blinker',
		'requests',
		'aiohttp',
		'requests-http-signature',
		'aiozipstream',
		'email-validator',
		'croniter',
		'azure-storage-blob',
		'asgi-lifespan==2.*',
		'yappi',
		'python-multipart',
		'aiofiles',
		'httpx',
		'common_py @ git+https://app_controller:MzJwN_VwwEyVmtj22LXx@gitlab.com/ptl/common_py.git',
	],
	extras_require={
		'dev': [
			'setuptools',
			'ruff',
			'pytest',
			'pytest-docker',
			'pytest-mock',
			'pytest-asyncio',
			'yappi',
			'responses',
			'aioresponses',
			'datamodel-code-generator[http]'
		]
	},
	package_data={'': ['config.yml', 'data/*']},
)
