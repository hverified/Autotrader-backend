from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    APP_NAME: str

    MONGO_URI: str
    MONGO_DB: str
    MONGO_COLLECTION: str

    TRADE_CAP: int
    BASE_CURRENCY: str

    CHARTINK_URL: str
    CHARTINK_SCAN_CLAUSE: str

    BACKEND_HOST: str
    BACKEND_PORT: int

    SHORTLIST_CRON: str
    BUY_CRON: str
    EOD_MARK_TO_SELL_CRON: str
    EXECUTE_SELL_CRON: str

    class Config:
        env_file = ".env"


settings = Settings()
