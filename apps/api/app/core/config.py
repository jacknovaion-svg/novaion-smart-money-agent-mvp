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
    shadow_trading_enabled: bool = False
    v2_alpha_validation_enabled: bool = False
    v3_enabled: bool = False
    shadow_v3_cutover_at: str = ""
    shadow_v3_version: str = "v3.0"
    v3_starting_balance: float = 100
    v3_margin_usd: float = 20
    v3_max_position_usd: float = 50
    v3_max_leverage: float = 3
    v3_min_notional: float = 10
    v3_fill_fraction: float = 1
    v3_execution_delay_seconds: int = 5
    v3_signal_max_age_seconds: int = 900
    v3_quote_max_age_seconds: int = 60
    v3_sync_max_age_seconds: int = 900
    v3_min_signal_score: float = 60
    v3_min_copyability: float = 40
    v3_min_change_usd: float = 100
    v3_min_change_pct: float = 0.01
    v3_min_samples: int = 30
    v3_min_active_days: int = 7
    v3_min_account_equity: float = 100
    v3_min_forward_closed: int = 20
    v3_lifecycle_hours: int = 24
    v3_discovery_limit: int = 50
    v3_discovery_url: str = "https://arena.freedomcore.io/"
    v3_request_interval_seconds: float = 0.5
    v3_score_pnl_weight: float = 20
    v3_score_pf_weight: float = 15
    v3_score_expectancy_weight: float = 10
    v3_score_consistency_weight: float = 20
    v3_score_concentration_weight: float = 10
    v3_score_activity_weight: float = 10
    v3_score_risk_weight: float = 15
    v3_tier_s: float = 90
    v3_tier_a: float = 80
    v3_tier_b: float = 60
    v3_tier_c: float = 40
    v3_telegram_min_score: float = 80
    v3_trend_threshold: float = 0.03
    v3_volatility_threshold: float = 0.02
    v3_min_validation_closed: int = 30
    v3_max_spread_pct: float = 0.005
    v3_telegram_pnl_usd: float = 10
    v3_evaluation_cache_seconds: int = 300

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
