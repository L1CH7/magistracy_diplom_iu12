from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    DATA_PROCESSOR_URL: str = "http://data-processor:8000"
    ROUTER_URL: str = "http://router:8000"
    LOG_LEVEL: str = "INFO"

    class Config:
        env_file = ".env"

settings = Settings()
