"""Application settings, loaded from the environment (never hard-coded).

Only the read-only ``PUBLIC_DATABASE_URL`` is used to reach PostgreSQL — the app
never holds a read-write connection (Decisions_Log D-005). Moving to BRERC
production is a change to this one URL.
"""

from __future__ import annotations

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # --- Database (read-only role) -----------------------------------------
    public_database_url: str = Field(
        default="postgresql://brerc_readonly:change_me@localhost:5432/brerc",
        alias="PUBLIC_DATABASE_URL",
    )
    db_pool_min_size: int = Field(default=1, alias="DB_POOL_MIN_SIZE")
    db_pool_max_size: int = Field(default=8, alias="DB_POOL_MAX_SIZE")

    # --- Query safety limits (also enforced at the DB role) ----------------
    api_max_rows: int = Field(default=5000, alias="API_MAX_ROWS")
    api_statement_timeout_ms: int = Field(default=5000, alias="API_STATEMENT_TIMEOUT_MS")

    # --- CORS ---------------------------------------------------------------
    # Comma-separated origins. Same-origin production needs none; dev allows Vite.
    api_cors_origins: str = Field(default="http://localhost:5173", alias="API_CORS_ORIGINS")

    # --- Species-info proxy -------------------------------------------------
    species_info_user_agent: str = Field(
        default="BRERC-Dashboard/0.1 (+https://www.brerc.org.uk; contact@example.org)",
        alias="SPECIES_INFO_USER_AGENT",
    )
    species_info_cache_ttl_days: int = Field(default=30, alias="SPECIES_INFO_CACHE_TTL_DAYS")
    species_info_timeout_s: float = Field(default=6.0, alias="SPECIES_INFO_TIMEOUT_S")
    # Allowed image licences (fail-closed). Default is the commercial-safe set
    # recommended in Data_Governance_and_Compliance.md §4 (CC0 / CC BY / public
    # domain). Add "cc-by-sa" only if the site will remain non-commercial.
    allowed_image_licences: str = Field(
        default="cc0,cc-by,public-domain", alias="ALLOWED_IMAGE_LICENCES"
    )

    # --- Internal data-quality dashboard (SECONDARY, access-controlled) ------
    # Off by default. When enabled it exposes /internal/* endpoints that read the
    # PRECISE data (incl. Recorder1 PII) via the brerc_internal_ro role. It must
    # be reachable only on the internal network / behind SSO — never through the
    # public proxy. HTTP Basic auth here is a minimal gate, not a substitute for
    # the council's own authentication.
    internal_enabled: bool = Field(default=False, alias="INTERNAL_ENABLED")
    internal_database_url: str | None = Field(default=None, alias="INTERNAL_DATABASE_URL")
    internal_basic_auth_user: str = Field(default="", alias="INTERNAL_BASIC_AUTH_USER")
    internal_basic_auth_password: str = Field(default="", alias="INTERNAL_BASIC_AUTH_PASSWORD")

    @property
    def internal_ready(self) -> bool:
        """True only if internal mode is fully and safely configured (fail-closed)."""
        return bool(
            self.internal_enabled
            and self.internal_database_url
            and self.internal_basic_auth_user
            and self.internal_basic_auth_password
        )

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.api_cors_origins.split(",") if o.strip()]

    @property
    def allowed_licence_set(self) -> set[str]:
        return {x.strip().lower() for x in self.allowed_image_licences.split(",") if x.strip()}

    @property
    def statement_timeout_s(self) -> float:
        return self.api_statement_timeout_ms / 1000.0


_settings: Settings | None = None


def get_settings() -> Settings:
    """Return a cached Settings instance."""
    global _settings
    if _settings is None:
        _settings = Settings()
    return _settings
