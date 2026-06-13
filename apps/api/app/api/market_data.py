import json

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.database import get_db
from app.models.market_data import WalletFill, WalletMetric, WalletOrderSnapshot, WalletPositionSnapshot
from app.models.wallet import Wallet
from app.schemas.auth import CurrentUser
from app.schemas.market_data import MarketRefreshResult, WalletMarketDataRead, WalletRankingItem
from app.services.metrics_service import metric_to_dict
from app.services.wallet_sync_service import sync_enabled_hyperliquid_wallets, sync_wallet_market_data


router = APIRouter(prefix="/market-data", tags=["market-data"])


@router.post("/refresh", response_model=MarketRefreshResult)
def refresh_all(
    db: Session = Depends(get_db),
    _user: CurrentUser = Depends(get_current_user),
) -> dict:
    return sync_enabled_hyperliquid_wallets(db)


@router.get("/wallet-metrics", response_model=list[WalletRankingItem])
def wallet_metrics(
    db: Session = Depends(get_db),
    _user: CurrentUser = Depends(get_current_user),
) -> list[WalletRankingItem]:
    wallets = db.query(Wallet).filter(Wallet.status != "deleted").order_by(Wallet.created_at.desc()).all()
    items = []
    for wallet in wallets:
        metric = db.query(WalletMetric).filter(WalletMetric.wallet_id == wallet.id).first()
        items.append(
            WalletRankingItem(
                wallet_id=wallet.id,
                name=wallet.name,
                address=wallet.address,
                tags=wallet.tags,
                manual_score=wallet.manual_score,
                total_trades=metric.total_trades if metric else 0,
                trades_30d=metric.trades_30d if metric else 0,
                realized_pnl=metric.realized_pnl if metric else 0,
                unrealized_pnl=metric.unrealized_pnl if metric else 0,
                win_rate=metric.win_rate if metric else 0,
                profit_factor=metric.profit_factor if metric else 0,
                last_trade_at=metric.last_trade_at if metric else None,
            )
        )
    return items


@router.post("/wallets/{wallet_id}/refresh", response_model=MarketRefreshResult)
def refresh_wallet(
    wallet_id: int,
    db: Session = Depends(get_db),
    _user: CurrentUser = Depends(get_current_user),
) -> dict:
    wallet = db.get(Wallet, wallet_id)
    if not wallet or wallet.status == "deleted":
        raise HTTPException(status_code=404, detail="Wallet not found")
    if wallet.platform != "hyperliquid":
        raise HTTPException(status_code=400, detail="Only Hyperliquid wallets can be synced in Part 2")
    result = sync_wallet_market_data(db, wallet)
    return {"synced_wallets": 1, "fills_inserted": result["fills_inserted"], "errors": []}


@router.get("/wallets/{wallet_id}", response_model=WalletMarketDataRead)
def wallet_market_data(
    wallet_id: int,
    db: Session = Depends(get_db),
    _user: CurrentUser = Depends(get_current_user),
) -> dict:
    wallet = db.get(Wallet, wallet_id)
    if not wallet or wallet.status == "deleted":
        raise HTTPException(status_code=404, detail="Wallet not found")

    fills = (
        db.query(WalletFill)
        .filter(WalletFill.wallet_id == wallet.id)
        .order_by(WalletFill.trade_time.desc())
        .limit(100)
        .all()
    )
    position_snapshot = (
        db.query(WalletPositionSnapshot)
        .filter(WalletPositionSnapshot.wallet_id == wallet.id)
        .order_by(WalletPositionSnapshot.created_at.desc())
        .first()
    )
    order_snapshot = (
        db.query(WalletOrderSnapshot)
        .filter(WalletOrderSnapshot.wallet_id == wallet.id)
        .order_by(WalletOrderSnapshot.created_at.desc())
        .first()
    )
    metric = db.query(WalletMetric).filter(WalletMetric.wallet_id == wallet.id).first()
    return {
        "fills": fills,
        "positions": json.loads(position_snapshot.positions_json) if position_snapshot else [],
        "open_orders": json.loads(order_snapshot.raw_json) if order_snapshot else [],
        "metric": metric_to_dict(metric),
    }
