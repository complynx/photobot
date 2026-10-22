import yaml

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict
from datetime import timedelta

class EnvironmentSettings(BaseSettings):
    model_config = SettingsConfigDict(populate_by_name=True, extra="ignore")

class TelegramSettings(EnvironmentSettings):
    token: SecretStr = Field(validation_alias="TELEGRAM_TOKEN")

class LoggingSettings(EnvironmentSettings):
    level: str = Field("WARNING", validation_alias="LOGGING_LEVEL")

class ServerSettings(EnvironmentSettings):
    base: str
    port: int = Field(8080, validation_alias="SERVER_PORT")

class PhotoSettings(EnvironmentSettings):
    cpu_threads: int = Field(8)
    storage_path: str = Field("photos")
    cover_path: str|None = Field(None)
    conversation_timeout: timedelta = Field(timedelta(hours=2))
    admins: list[int] = []

class LocalizationSettings(EnvironmentSettings):
    path: str = Field("i18n/{locale}", validation_alias="LOCALIZATION_PATH")
    fallbacks: list[str] = Field(["en-US", "en"])
    file: str = Field("bot.ftl")

class UsersDB(EnvironmentSettings):
    address: str = Field("", validation_alias="BOT_MONGODB_ADDRESS")
    collection: str = Field("bot_users", validation_alias="BOT_MONGODB_COLLECTION")

class Config(EnvironmentSettings):
    telegram: TelegramSettings
    logging: LoggingSettings
    server: ServerSettings
    photo: PhotoSettings
    localization: LocalizationSettings
    users_db: UsersDB

    def __init__(self, filename:str="config/config.yaml"):
        # Load a YAML configuration file
        with open(filename, 'r') as f:
            conf = yaml.safe_load(f)
        
        super().__init__(**conf)
