def migrate_1_0_to_1_1(values):
    values["v"] = "1.1"
    values["pretty_name"] = values["name"].title()
    return values


def migrate_1_1_to_1_2(values):
    values["v"] = "1.2"
    return values


migrations = {
    "1.0": migrate_1_0_to_1_1,
    "1.1": migrate_1_1_to_1_2,
}
