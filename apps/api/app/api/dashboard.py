from sqlalchemy.orm import Session
from fastapi import APIRouter, Depends

from app.api.deps import get_current_user
from app.core.database import get_db
from app.models.market_data import WalletMetric
from app.models.wallet import Wallet
from app.schemas.auth import CurrentUser
from app.schemas.dashboard import DashboardSummary
from app.schemas.market_data import WalletRankingItem


router = APIRouter(prefix="/dashboard", tags=["dashboard"])


@router.get("/summary", response_model=DashboardSummary)
def summary(
    db: Session = Depends(get_db),
    _user: CurrentUser = Depends(get_current_user),
) -> DashboardSummary:
    wallets = db.query(Wallet).all()
    ranking_rows = (
        db.query(Wallet, WalletMetric)
        .join(WalletMetric, WalletMetric.wallet_id == Wallet.id)
        .filter(Wallet.status != "deleted")
        .order_by(WalletMetric.realized_pnl.desc(), WalletMetric.win_rate.desc())
        .limit(10)
        .all()
    )
    rankings = [
        WalletRankingItem(
            wallet_id=wallet.id,
            name=wallet.name,
            address=wallet.address,
            tags=wallet.tags,
            manual_score=wallet.manual_score,
            total_trades=metric.total_trades,
            trades_30d=metric.trades_30d,
            realized_pnl=metric.realized_pnl,
            unrealized_pnl=metric.unrealized_pnl,
            win_rate=metric.win_rate,
            profit_factor=metric.profit_factor,
            last_trade_at=metric.last_trade_at,
        )
        for wallet, metric in ranking_rows
    ]
    return DashboardSummary(
        total_wallets=len([wallet for wallet in wallets if wallet.status != "deleted"]),
        active_wallets=len([wallet for wallet in wallets if wallet.status == "active"]),
        disabled_wallets=len([wallet for wallet in wallets if wallet.status == "disabled"]),
        deleted_wallets=len([wallet for wallet in wallets if wallet.status == "deleted"]),
        hyperliquid_wallets=len(
            [wallet for wallet in wallets if wallet.status != "deleted" and wallet.platform == "hyperliquid"]
        ),
        polymarket_wallets=len(
            [wallet for wallet in wallets if wallet.status != "deleted" and wallet.platform == "polymarket"]
        ),
        rankings=rankings,
    )
