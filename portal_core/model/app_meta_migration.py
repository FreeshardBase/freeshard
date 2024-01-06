def migrate_1_0_to_1_1(values):
	values['v'] = '1.1'
	values['pretty_name'] = values['name'].title()
	return values


migrations = {
	'1.0': migrate_1_0_to_1_1,
}
