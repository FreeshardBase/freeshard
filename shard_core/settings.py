from pathlib import Path
from typing import Optional

from pydantic import BaseModel
from pydantic_settings import BaseSettings, SettingsConfigDict, TomlConfigSettingsSource

_settings_instance: Optional["Settings"] = None


class DnsSettings(BaseModel):
    zone: str
    prefix_length: int = 6


class BackupTimingSettings(BaseModel):
    base_schedule: str
    max_random_delay: int


class BackupSettings(BaseModel):
    directories: list[str]
    timing: BackupTimingSettings
    included_globs: list[str] = []


class ServicesSettings(BaseModel):
    backup: BackupSettings


class TraefikSettings(BaseModel):
    acme_email: str
    disable_ssl: bool = False


class AppStoreSettings(BaseModel):
    base_url: str
    container_name: str


class RegistrySettings(BaseModel):
    uri: str
    username: str
    password: str


class AppLifecycleSettings(BaseModel):
    refresh_interval: int = 10


class AppLastAccessSettings(BaseModel):
    max_update_frequency: int = 60


class AppUsageReportingSettings(BaseModel):
    tracking_schedule: str
    reporting_schedule: str


class AppPruningSettings(BaseModel):
    schedule: str
    max_age: int = 24
    enabled: bool = False


class AppsSettings(BaseModel):
    app_store: AppStoreSettings
    registries: list[RegistrySettings] = []
    lifecycle: AppLifecycleSettings = AppLifecycleSettings()
    initial_apps: list[str] = []
    last_access: AppLastAccessSettings = AppLastAccessSettings()
    usage_reporting: AppUsageReportingSettings
    pruning: AppPruningSettings


class TelemetrySettings(BaseModel):
    enabled: bool = False
    send_interval_seconds: int = 300


class ManagementSettings(BaseModel):
    api_url: str


class PortalControllerSettings(BaseModel):
    base_url: str


class FreeshardControllerSettings(BaseModel):
    base_url: str


class LogSettings(BaseModel):
    levels: dict[str, str] = {}


class TerminalSettings(BaseModel):
    pairing_code_deadline: int = 600
    jwt_secret_length: int = 64


class TestsSettings(BaseModel):
    pass


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="FREESHARD_",
        env_nested_delimiter="__",
    )

    path_root: str = "/"
    path_root_host: str = "/home/shard"
    dns: DnsSettings
    services: ServicesSettings
    traefik: TraefikSettings
    apps: AppsSettings
    telemetry: TelemetrySettings = TelemetrySettings()
    management: ManagementSettings
    portal_controller: Optional[PortalControllerSettings] = None
    freeshard_controller: FreeshardControllerSettings
    log: LogSettings = LogSettings()
    terminal: TerminalSettings = TerminalSettings()
    tests: TestsSettings = TestsSettings()

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls,
        init_settings,
        env_settings,
        dotenv_settings,
        file_secret_settings,
    ):
        # Build sources with separate TomlConfigSettingsSource per file so that
        # override files only replace individual fields, not entire nested sections.
        sources = [init_settings, env_settings]
        for toml_file in reversed(cls._override_toml_files()):
            sources.append(TomlConfigSettingsSource(settings_cls, toml_file=toml_file))
        sources.append(TomlConfigSettingsSource(settings_cls, toml_file="config.toml"))
        return tuple(sources)

    @classmethod
    def _override_toml_files(cls) -> list[str]:
        """Return additional TOML files to overlay on top of config.toml (highest priority last)."""
        files = []
        if Path("local_config.toml").exists():
            files.append("local_config.toml")
        return files


def settings() -> Settings:
    global _settings_instance
    if _settings_instance is None:
        _settings_instance = Settings()
    return _settings_instance


def set_settings(instance: Settings) -> None:
    global _settings_instance
    _settings_instance = instance


def reset_settings() -> None:
    global _settings_instance
    _settings_instance = None
