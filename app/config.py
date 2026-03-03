from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # Database
    database_url: str = "sqlite+aiosqlite:///./data/watchservice.db"

    # Security
    run_token: str = ""

    # Google Sheets
    google_sheet_id: str = ""
    google_sheet_tab: str = "watches"
    google_service_account_json: str = ""   # path to file
    google_service_account_key: str = ""    # inline JSON alternative

    # Search APIs
    serper_api_key: str = ""
    ebay_client_id: str = ""
    ebay_client_secret: str = ""
    ebay_verification_token: str = ""       # chosen by you, registered in eBay dev portal
    ebay_deletion_endpoint_url: str = ""    # full public URL of the deletion endpoint

    # LLM
    anthropic_api_key: str = ""

    # Scheduler
    schedule_interval_hours: int = 6

    # App
    app_port: int = 8000
    log_level: str = "INFO"


settings = Settings()
