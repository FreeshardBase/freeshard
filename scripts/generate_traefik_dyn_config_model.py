import urllib.parse
from pathlib import Path

import datamodel_code_generator

raise Exception('Do no use! Output file was manually changed by adding authResponseHeadersRegex.')

output_path = Path(__file__).parent.parent / 'portal_core' / 'model' / 'traefik_dyn_config.py'
input_ = urllib.parse.urlparse(
	'https://json.schemastore.org/traefik-v2-file-provider.json')

print(output_path)
datamodel_code_generator.generate(
	input_file_type='jsonschema',
	input_=input_,
	output=output_path
)
