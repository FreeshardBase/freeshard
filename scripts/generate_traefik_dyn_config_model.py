import urllib.parse
from pathlib import Path

import datamodel_code_generator

output_path = Path(__file__).parent.parent / 'portal_core' / 'model' / 'traefik_dyn_config.py'
input_ = urllib.parse.urlparse(
	'https://json.schemastore.org/traefik-v2-file-provider.json')

print(output_path)
datamodel_code_generator.generate(
	input_file_type=datamodel_code_generator.InputFileType.JsonSchema,
	input_=input_,
	output_model_type=datamodel_code_generator.DataModelType.PydanticV2BaseModel,
	output=output_path,
	field_constraints=True,
)
