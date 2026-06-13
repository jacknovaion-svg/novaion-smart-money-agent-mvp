from app.core.database import SessionLocal, init_db
from app.models.signal import Signal
from app.models.wallet import Wallet
from app.services.paper_trading_service import add_signal_to_paper
from app.services.system_log_service import write_log


def seed() -> None:
    init_db()
    db = SessionLocal()
    try:
        wallet = db.query(Wallet).filter(Wallet.address == "0x0000000000000000000000000000000000000000").first()
        if not wallet:
            wallet = Wallet(
                address="0x0000000000000000000000000000000000000000",
                platform="hyperliquid",
                name="Demo Hyperliquid Wallet",
                tags="demo, BTC高手",
                manual_score=75,
                status="active",
                notes="Seed wallet for internal MVP testing.",
            )
            db.add(wallet)
            db.commit()
            db.refresh(wallet)

        signal = db.query(Signal).filter(Signal.dedupe_key == "seed-demo-btc-open").first()
        if not signal:
            signal = Signal(
                wallet_id=wallet.id,
                platform="hyperliquid",
                symbol="BTC",
                signal_type="open",
                side="long",
                source_size=50000,
                source_leverage=10,
                source_entry_price=65000,
                current_price=65000,
                confidence_score=78,
                risk_score=68,
                suggested_action="Only simulate. Do not live trade.",
                suggested_size_usd=20,
                reason="Seed demo signal for paper-trading workflow verification.",
                status="new",
                source_trade_id="seed-demo-btc-open",
                dedupe_key="seed-demo-btc-open",
            )
            db.add(signal)
            db.commit()
            db.refresh(signal)
            add_signal_to_paper(db, signal)

        write_log(db, level="info", module="seed", message="Seed data ready")
    finally:
        db.close()


if __name__ == "__main__":
    seed()
