from pydantic_settings import BaseSettings
from pathlib import Path


BACKEND_ROOT = Path(__file__).parent.parent.resolve()
DEFAULT_DATA_DIR = BACKEND_ROOT / "data"


class Settings(BaseSettings):
    app_env: str = "development"
    # "*" = allow any origin; otherwise comma-separated list of exact origins
    cors_origins: str = "*"

    # SQLAlchemy URL. Examples:
    #   sqlite:///./data/agentflow.db
    #   postgresql+psycopg2://user:pass@host:5432/dbname
    #   mysql+pymysql://user:pass@host/dbname
    database_url: str = f"sqlite:///{(DEFAULT_DATA_DIR / 'agentflow.db').as_posix()}"

    # Where per-script .venv directories live. Override in docker via env.
    data_dir: str = str(DEFAULT_DATA_DIR / "scripts")

    # Public base URL of the deployment, e.g. "https://agentflow.example.com".
    # Used to build absolute callback URLs (notably the MCP OAuth redirect_uri).
    # Leave blank for local/dev — the request's own base URL is used instead.
    # MUST be set (to an https URL) behind a reverse proxy, or OAuth providers
    # will reject the http/internal redirect_uri during client registration.
    public_base_url: str = ""

    # Loopback base URL the in-browser "AI 脚本助手" uses to reach THIS server's
    # own /mcp gateway (the assistant runs as a script subprocess and pulls the
    # write→run→debug tools over MCP from us). Defaults to localhost:8000 — the
    # most reliable target since it skips any reverse proxy / TLS. Override via
    # SELF_BASE_URL only if uvicorn binds a different port.
    self_base_url: str = "http://127.0.0.1:8000"

    # ── Auth ──────────────────────────────────────────────────────────────────
    # Secret used to sign admin session tokens. If blank, a random key is
    # generated once and persisted to data/.secret_key so tokens survive restart.
    # Set SECRET_KEY in production (e.g. behind multiple replicas) for stability.
    secret_key: str = ""
    # How long an admin login stays valid (hours).
    session_ttl_hours: int = 168  # 7 days
    # Mark the session cookie Secure (https-only). Enable in production over TLS.
    cookie_secure: bool = False

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}

    @property
    def cors_origins_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",")]


settings = Settings()

DATA_DIR = Path(settings.data_dir)
DATA_DIR.mkdir(parents=True, exist_ok=True)
