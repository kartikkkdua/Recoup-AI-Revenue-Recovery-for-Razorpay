from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    razorpay_key_id: str = "rzp_test_placeholder"
    razorpay_key_secret: str = "placeholder"
    razorpay_webhook_secret: str = "placeholder"
    gemini_api_key: str = ""
    database_url: str = "sqlite+aiosqlite:///./recoup.db"
    cors_origin: str = "http://localhost:3000"
    llm_model: str = "gemini-2.0-flash"
    # Toggle the ML pipeline (contextual bandit + feature store + semantic
    # memory). Off by default so the deterministic rules-only baseline stays
    # reachable for the panel comparison.
    use_ml: bool = True


settings = Settings()
