from pathlib import Path

import gconf

gconf.set_env_prefix("FREESHARD")
gconf.load(
    Path(__file__).parent.parent / "config.yml", Path(__file__).parent / "config.yml"
)
