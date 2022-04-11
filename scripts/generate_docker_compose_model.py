import urllib.parse
from pathlib import Path

import datamodel_code_generator

output_path = Path(__file__).parent.parent / 'portal_core' / 'model' / 'docker_compose.py'
input_ = urllib.parse.urlparse(
	'https://raw.githubusercontent.com/compose-spec/compose-spec/master/schema/compose-spec.json')

print(output_path)
datamodel_code_generator.generate(
	input_file_type='jsonschema',
	input_=input_,
	output=output_path
)
