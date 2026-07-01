from functools import lru_cache
from typing import List

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "NOVAION Smart Money Agent MVP"
    environment: str = "local"
    secret_key: str = "change-me-before-deploy"
    access_token_expire_minutes: int = 1440
    admin_email: str = "admin@novaion.ai"
    admin_password: str = "Novaion@123"
    database_url: str = "sqlite:///./data/novaion.db"
    backend_cors_origins: List[str] = [
        "http://localhost:5173",
        "http://127.0.0.1:5173",
    ]

    telegram_bot_token: str = ""
    telegram_chat_id: str = ""

    hyperliquid_api_base_url: str = "https://api.hyperliquid.xyz"
    hyperliquid_sync_enabled: bool = True
    hyperliquid_initial_lookback_days: int = 30
    scheduler_enabled: bool = True
    discovery_enabled: bool = True
    discovery_source_urls: str = ""
    discovery_local_source_path: str = "./data/discovery_wallets.txt"
    discovery_auto_add_enabled: bool = False
    discovery_min_score_to_add: int = 80
    smart_min_trade_count_30d: int = 30
    smart_min_win_rate: float = 0.55
    smart_min_profit_factor: float = 1.2
    smart_max_single_loss_pct: float = 0.30
    smart_soft_watch_min_gross_profit: float = 1000
    smart_soft_watch_min_trade_count_30d: int = 20
    smart_money_telegram_boss_mode: bool = True
    smart_money_telegram_aggregation_minutes: int = 30
    alert_cooldown_minutes: int = 60
    paper_account_starting_balance_usd: float = 100
    paper_trading_telegram_boss_mode: bool = True
    paper_taker_fee_rate: float = 0.0005
    paper_slippage_rate: float = 0.001
    paper_max_position_usd: float = 50
    paper_trading_cutover_at: str = ""
    task_lock_stale_minutes: int = 30
    validation_mode: bool = True
    validation_days: int = 7

    enable_live_trading: bool = False
    require_manual_approval: bool = True
    max_live_order_usd: int = 20
    max_daily_live_loss_usd: int = 50
    emergency_stop: bool = True

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    @field_validator("backend_cors_origins", mode="before")
    @classmethod
    def parse_cors_origins(cls, value):
        if isinstance(value, str):
            return [origin.strip() for origin in value.split(",") if origin.strip()]
        return value


@lru_cache
def get_settings() -> Settings:
    return Settings()
