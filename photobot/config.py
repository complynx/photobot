import yaml

from pydantic import BaseSettings, Field, SecretStr 
from datetime import timedelta

class TelegramSettings(BaseSettings):
    token: SecretStr = Field(env="TELEGRAM_TOKEN")

class LoggingSettings(BaseSettings):
    level: str = Field("WARNING", env="LOGGING_LEVEL")

class ServerSettings(BaseSettings):
    base: str
    port: int = Field(8080, env="SERVER_PORT")

class PhotoSettings(BaseSettings):
    cpu_threads: int = Field(8)
    storage_path: str = Field("photos")
    conversation_timeout: timedelta = Field(timedelta(hours=2))

class LocalizationSettings(BaseSettings):
    path: str = Field("i18n/{locale}", env="LOCALIZATION_PATH")
    fallbacks: list[str] = Field(["en-US", "en"])
    file: str = Field("bot.ftl")

class Config(BaseSettings):
    telegram: TelegramSettings
    logging: LoggingSettings
    server: ServerSettings
    photo: PhotoSettings
    localization: LocalizationSettings

    def __init__(self, filename:str="config/config.yaml"):
        # Load a YAML configuration file
        with open(filename, 'r') as f:
            conf = yaml.safe_load(f)
        
        super().__init__(**conf)
