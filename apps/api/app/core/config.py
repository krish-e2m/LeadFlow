import json
from typing import List, Optional, Union

from pydantic import field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(".env", "../../.env"),
        env_file_encoding="utf-8",
        case_sensitive=True,
        extra="ignore",
    )

    # Global & Application
    ENVIRONMENT: str = "development"
    LOG_LEVEL: str = "INFO"
    APP_NAME: str = "LeadFlow"
    BACKEND_CORS_ORIGINS: List[str] = [
        "http://localhost:3000",
        "http://127.0.0.1:3000",
    ]
    ALLOWED_HOSTS: List[str] = ["localhost", "127.0.0.1", "api", "web"]

    @field_validator("BACKEND_CORS_ORIGINS", mode="before")
    @classmethod
    def assemble_cors_origins(cls, v: Union[str, List[str]]) -> List[str]:
        if isinstance(v, str):
            try:
                return json.loads(v)
            except Exception:
                return [i.strip() for i in v.split(",") if i.strip()]
        return v

    # Security & JWT
    JWT_SECRET_KEY: str = "leadflow-insecure-dev-secret-key-change-in-production-min-32-chars"
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 15
    REFRESH_TOKEN_EXPIRE_DAYS: int = 7

    # Session Cookies & CSRF
    COOKIE_ACCESS_NAME: str = "leadflow_access_token"
    COOKIE_REFRESH_NAME: str = "leadflow_refresh_token"
    COOKIE_CSRF_NAME: str = "leadflow_csrf_token"
    COOKIE_DOMAIN: Optional[str] = None
    COOKIE_SAMESITE: str = "lax"
    COOKIE_SECURE: Optional[bool] = None

    @property
    def is_cookie_secure(self) -> bool:
        if self.COOKIE_SECURE is not None:
            return self.COOKIE_SECURE
        return self.ENVIRONMENT.lower() == "production"

    @model_validator(mode="after")
    def validate_production_security(self) -> "Settings":
        insecure_keys = {
            "leadflow-insecure-dev-secret-key-change-in-production-min-32-chars",
            "secret",
            "changeme",
        }
        if self.ENVIRONMENT.lower() == "production":
            if self.JWT_SECRET_KEY in insecure_keys:
                raise ValueError("Insecure default JWT_SECRET_KEY is forbidden in production environment.")
            if len(self.JWT_SECRET_KEY) < 32:
                raise ValueError("JWT_SECRET_KEY must be at least 32 characters long in production.")
        return self

    # PostgreSQL Database
    POSTGRES_HOST: str = "localhost"
    POSTGRES_PORT: int = 5432
    POSTGRES_DB: str = "leadflow"
    POSTGRES_USER: str = "leadflow_admin"
    POSTGRES_PASSWORD: str = "leadflow_admin_password"
    POSTGRES_APP_USER: str = "leadflow_app"
    POSTGRES_APP_PASSWORD: str = "leadflow_app_password"

    POSTGRES_ADMIN_URL: Optional[str] = None
    DATABASE_MIGRATION_URL: Optional[str] = None
    DATABASE_ADMIN_URL: Optional[str] = None

    DATABASE_URL: str = (
        "postgresql+asyncpg://leadflow_app:leadflow_app_password@localhost:5432/leadflow"
    )
    DATABASE_APP_URL: str = (
        "postgresql+asyncpg://leadflow_app:leadflow_app_password@localhost:5432/leadflow"
    )

    @property
    def migration_database_url(self) -> str:
        """Privileged connection URL used strictly by Alembic migrations."""
        if self.POSTGRES_ADMIN_URL:
            return self.POSTGRES_ADMIN_URL
        if self.DATABASE_MIGRATION_URL:
            return self.DATABASE_MIGRATION_URL
        if self.DATABASE_ADMIN_URL:
            return self.DATABASE_ADMIN_URL
        return (
            f"postgresql+asyncpg://{self.POSTGRES_USER}:{self.POSTGRES_PASSWORD}@"
            f"{self.POSTGRES_HOST}:{self.POSTGRES_PORT}/{self.POSTGRES_DB}"
        )

    @property
    def runtime_database_url(self) -> str:
        """Least-privilege connection URL used by FastAPI application and worker."""
        if self.DATABASE_APP_URL:
            return self.DATABASE_APP_URL
        return self.DATABASE_URL

    # Redis & ARQ Worker
    REDIS_HOST: str = "localhost"
    REDIS_PORT: int = 6379
    REDIS_PASSWORD: str = ""
    REDIS_DB: int = 0
    REDIS_URL: str = "redis://localhost:6379/0"
    ARQ_MAX_JOBS: int = 20
    ARQ_JOB_TIMEOUT: int = 1800
    DEFAULT_SEARCH_LEAD_LIMIT: int = 100
    MAX_SEARCH_LEAD_LIMIT: int = 500
    # Leads enriched in parallel inside one search run. Each lead already fans out to its own
    # collectors, so keep this modest to stay under provider rate limits.
    SEARCH_LEAD_CONCURRENCY: int = 4
    # A Qualified-level score built on fewer available signals than this is held in Review.
    SCORING_MIN_SIGNALS_FOR_QUALIFIED: int = 6

    # Quotas & Limits (Per-Org Defaults)
    QUOTA_LEADS_PER_MONTH: int = 100
    QUOTA_LEADS_PER_SEARCH: int = 500
    QUOTA_CONCURRENT_RUNS: int = 2
    QUOTA_CONTACT_REVEALS_PER_DAY: int = 100
    QUOTA_DRAFT_GENERATION_PER_DAY: int = 200
    QUOTA_LLM_MONTHLY_CEILING_USD: float = 10.0
    MAX_BULK_BATCH_SIZE: int = 100
    # Approving a lead queues one AI email draft for it (uses the daily draft quota).
    AUTO_DRAFT_ON_APPROVAL: bool = True

    # External Provider 1: Hunter.io (Domain Search, Company Enrichment, Contacts & Verification)
    HUNTER_API_KEY: str = ""
    HUNTER_BASE_URL: str = "https://api.hunter.io/v2"
    HUNTER_ENABLED: bool = True
    HUNTER_AUTO_REVEAL_CONTACTS: bool = False

    # Deprecated / Inactive Provider: Apollo.io (Retired in favor of Hunter.io)
    APOLLO_API_KEY: str = ""
    APOLLO_BASE_URL: str = "https://api.apollo.io/v1"
    APOLLO_AUTO_REVEAL_CONTACTS: bool = False

    # External Provider 2: OpenRouter
    OPENROUTER_API_KEY: str = ""
    OPENROUTER_BASE_URL: str = "https://openrouter.ai/api/v1"
    OPENROUTER_DEFAULT_MODEL: str = "anthropic/claude-sonnet-5.5"
    OPENROUTER_FAST_MODEL: str = "openai/gpt-4o-mini"
    OPENROUTER_SITE_NAME: str = "LeadFlow"
    OPENROUTER_SITE_URL: str = "https://leadflow.local"

    # External Provider 3: HubSpot
    HUBSPOT_ACCESS_TOKEN: str = ""
    HUBSPOT_PORTAL_ID: str = ""
    HUBSPOT_ENABLED: bool = False

    # External Provider 4: Google PageSpeed Insights
    PAGESPEED_API_KEY: str = ""
    PAGESPEED_BASE_URL: str = "https://pagespeedonline.googleapis.com/pagespeedonline/v5/runPagespeed"

    # External Provider 5: Google Places (Unconfigured Gracefully)
    GOOGLE_PLACES_API_KEY: str = ""
    GOOGLE_PLACES_ENABLED: bool = False

    # External Provider 6: DataForSEO (Unconfigured Gracefully)
    DATAFORSEO_LOGIN: str = ""
    DATAFORSEO_PASSWORD: str = ""
    DATAFORSEO_ENABLED: bool = False

    # External Provider 7: Resend
    RESEND_API_KEY: str = ""
    RESEND_FROM_EMAIL: str = "notifications@leadflow.local"
    RESEND_ENABLED: bool = False

    # External Provider 8: SuperMemory
    SUPERMEMORY_API_KEY: str = ""
    SUPERMEMORY_ENABLED: bool = False

    # External Provider 9: Firecrawl (Headless JS Scraper & LLM Markdown Extraction)
    FIRECRAWL_API_KEY: str = ""
    FIRECRAWL_BASE_URL: str = "https://api.firecrawl.dev/v2"
    FIRECRAWL_ENABLED: bool = False
    FIRECRAWL_TIMEOUT_SECONDS: float = 15.0
    FIRECRAWL_MAX_SUBPAGES: int = 2

    # External Provider 10: SerpApi (Google Maps, Reviews, Business Reputation)
    SERPAPI_API_KEY: str = ""
    SERPAPI_BASE_URL: str = "https://serpapi.com"
    SERPAPI_ENABLED: bool = False

    # External Provider 11: Google OAuth 2.0
    GOOGLE_CLIENT_ID: str = ""
    GOOGLE_CLIENT_SECRET: str = ""
    GOOGLE_REDIRECT_URI: str = "http://localhost:8000/api/v1/auth/google/callback"
    GOOGLE_FRONTEND_REDIRECT_URL: str = "http://localhost:3000/dashboard"

    @property
    def is_google_auth_enabled(self) -> bool:
        return bool(self.GOOGLE_CLIENT_ID and self.GOOGLE_CLIENT_SECRET)


settings = Settings()
