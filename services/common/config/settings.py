from typing import Dict, List, Optional
from pydantic import BaseModel, HttpUrl
from pydantic_settings import BaseSettings, SettingsConfigDict

# --- Service Configuration Models ---

class ServiceConfig(BaseModel):
    """
    Configuration for a single internal microservice.
    URL should include protocol and port, e.g., 'http://router:8006'
    """
    url: str

class Services(BaseModel):
    """
    Registry of all available microservices.
    Attributes match Docker Compose service names (mostly).
    """
    router: ServiceConfig
    data_processor: ServiceConfig
    # Add other services here as they are created (e.g., coordinator)

class DatabaseConfig(BaseModel):
    """Database configuration."""
    host: str = "postgis"
    port: int = 5432
    name: str = "osm"
    user: str = "diplom"
    password: str = "diplom_pass"

class DataProcessorSettings(BaseModel):
    """Configuration for Data Processor service."""
    tile_size: float = 0.05
    cpu_cores: int = 0  # 0 means all available cores

# --- Main Settings Class ---

class Settings(BaseSettings):
    """
    Global Application Settings.
    
    Source of Truth: Environment Variables.
    Pattern: APP__<SECTION>__<FIELD>
    Example: APP__SERVICES__ROUTER__URL="http://router:8006"
    """
    services: Services
    db: DatabaseConfig = DatabaseConfig()
    data_processor_config: DataProcessorSettings = DataProcessorSettings()
    
    # Nested delimiter allows: APP__SERVICES__ROUTER__URL -> services.router.url
    model_config = SettingsConfigDict(
        env_prefix='APP__',
        env_nested_delimiter='__',
        case_sensitive=False,
        extra='ignore' # Ignore unknown env vars
    )

def load_settings() -> Settings:
    """Factory to load settings from environment."""
    return Settings()
