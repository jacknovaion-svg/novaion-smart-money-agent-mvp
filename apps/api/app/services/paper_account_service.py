from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models.signal import PaperTrade


def paper_account_metrics(db: Session) -> dict[str, Any]:
    settings = get_settings()
    starting_balance = float(settings.paper_account_starting_balance_usd)
    trades = db.query(PaperTrade).all()
    open_trades = [trade for trade in trades if trade.status == "open"]
    closed_trades = [trade for trade in trades if trade.status == "closed"]
    realized_pnl = round(sum(trade.pnl or 0 for trade in trades), 6)
    unrealized_pnl = round(sum(trade.unrealized_pnl or 0 for trade in open_trades), 6)
    used_margin = round(sum(trade.size_usd or 0 for trade in open_trades), 6)
    account_balance = round(starting_balance + realized_pnl, 6)
    account_equity = round(starting_balance + realized_pnl + unrealized_pnl, 6)
    available_funds_raw = round(account_equity - used_margin, 6)
    account_return_pct = round(((account_equity - starting_balance) / starting_balance * 100) if starting_balance else 0, 6)
    winning_closed = [trade for trade in closed_trades if (trade.pnl or 0) > 0]
    losing_closed = [trade for trade in closed_trades if (trade.pnl or 0) < 0]
    return {
        "starting_balance": starting_balance,
        "realized_pnl": realized_pnl,
        "unrealized_pnl": unrealized_pnl,
        "account_balance": account_balance,
        "account_equity": account_equity,
        "used_margin": used_margin,
        "available_funds": max(0, available_funds_raw),
        "available_funds_raw": available_funds_raw,
        "account_return_pct": account_return_pct,
        "open_trades": len(open_trades),
        "closed_trades": len(closed_trades),
        "winning_closed_trades": len(winning_closed),
        "losing_closed_trades": len(losing_closed),
        "calculated_at": datetime.now(timezone.utc).isoformat(),
    }


def trade_margin_return_pct(trade: PaperTrade) -> float | None:
    if trade.status != "open":
        return None
    if not trade.size_usd or trade.size_usd <= 0:
        return None
    return round((trade.unrealized_pnl or 0) / trade.size_usd * 100, 6)


def trade_notional(trade: PaperTrade) -> float:
    return round((trade.size_usd or 0) * (trade.leverage or 1), 6)


def boss_conclusion(metrics: dict[str, Any], *, failed_count: int = 0, core_error: bool = False) -> str:
    if failed_count > 0 and core_error:
        return "模拟盘运行异常，需要技术检查。"
    if metrics["closed_trades"] < 3:
        return "当前样本不足，继续模拟验证。"
    if metrics["account_return_pct"] <= -5:
        return "当前账户回撤较高，需要重点关注。"
    if -2 <= metrics["account_return_pct"] < 0:
        return "账户整体小幅亏损，暂不调整。"
    if metrics["account_return_pct"] > 0:
        return "账户整体盈利，继续观察稳定性。"
    return "账户目前出现一定亏损，需要继续观察风险。"
