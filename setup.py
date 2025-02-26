import logging

from setuptools import setup, find_packages

log = logging.getLogger(__name__)

setup(
	name='shard_core',
	version='0.33.0.dev0',
	packages=find_packages(),
	url='https://github.com/FreeshardBase/shard_core',
	author='Max von Tettenborn',
	author_email='contact@freeshard.net',
	description='Core software stack that manages all aspects of a Shard',
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
		'cryptography',
		'requests-http-signature',
		'aiozipstream',
		'email_validator',
		'croniter',
		'bitstring',
		'azure-storage-blob',
		'asgi-lifespan==2.*',
		'python-multipart',
		'aiofiles',
		'httpx',
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
