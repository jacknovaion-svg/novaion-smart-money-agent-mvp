from pydantic import BaseModel

from app.schemas.market_data import WalletRankingItem


class DashboardSummary(BaseModel):
    total_wallets: int
    active_wallets: int
    disabled_wallets: int
    deleted_wallets: int
    hyperliquid_wallets: int
    polymarket_wallets: int
    rankings: list[WalletRankingItem] = []
