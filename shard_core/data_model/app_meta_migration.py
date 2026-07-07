def migrate_1_0_to_1_1(values):
    values["v"] = "1.1"
    values["pretty_name"] = values["name"].title()
    return values


def migrate_1_1_to_1_2(values):
    values["v"] = "1.2"
    return values


def migrate_1_2_to_1_3(values):
    # Lifecycle rework for the PAUSED+PAGED tier: idle_time_for_shutdown
    # becomes idle_for_stop; idle_for_pause stays unset and falls back to the
    # global default. App-repository files are not regenerated — this runs on
    # every read of a v1.2 app_meta.json.
    lifecycle = values.get("lifecycle") or {}
    if not lifecycle.get("always_on"):
        idle_time_for_shutdown = lifecycle.pop("idle_time_for_shutdown", None)
        if idle_time_for_shutdown is not None:
            lifecycle["idle_for_stop"] = idle_time_for_shutdown
    values["lifecycle"] = lifecycle
    values["v"] = "1.3"
    return values


migrations = {
    "1.0": migrate_1_0_to_1_1,
    "1.1": migrate_1_1_to_1_2,
    "1.2": migrate_1_2_to_1_3,
}
