from pydantic_settings import BaseSettings
from pathlib import Path


BACKEND_ROOT = Path(__file__).parent.parent.resolve()
DEFAULT_DATA_DIR = BACKEND_ROOT / "data"


class Settings(BaseSettings):
    app_env: str = "development"
    # "*" = allow any origin; otherwise comma-separated list of exact origins
    cors_origins: str = "*"

    # SQLAlchemy URL. Examples:
    #   sqlite:///./data/opengraph.db
    #   postgresql+psycopg2://user:pass@host:5432/dbname
    #   mysql+pymysql://user:pass@host/dbname
    database_url: str = f"sqlite:///{(DEFAULT_DATA_DIR / 'opengraph.db').as_posix()}"

    # Where per-script .venv directories live. Override in docker via env.
    data_dir: str = str(DEFAULT_DATA_DIR / "scripts")

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}

    @property
    def cors_origins_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",")]


settings = Settings()

DATA_DIR = Path(settings.data_dir)
DATA_DIR.mkdir(parents=True, exist_ok=True)
