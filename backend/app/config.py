from pydantic_settings import BaseSettings
from pathlib import Path


class Settings(BaseSettings):
    app_env: str = "development"
    cors_origins: str = "http://localhost:3000"

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}

    @property
    def cors_origins_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",")]


settings = Settings()

BACKEND_ROOT = Path(__file__).parent.parent.resolve()
DATA_DIR = BACKEND_ROOT / "data" / "scripts"
DATA_DIR.mkdir(parents=True, exist_ok=True)
