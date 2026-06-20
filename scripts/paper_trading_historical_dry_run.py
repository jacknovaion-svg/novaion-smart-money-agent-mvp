import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "apps" / "api"))


def main() -> None:
    from app.core.database import SessionLocal, init_db
    from app.services.paper_trading_processor import (
        generate_historical_dry_run_report,
        get_or_create_paper_trading_cutover,
    )

    init_db()
    db = SessionLocal()
    try:
        cutover_at = get_or_create_paper_trading_cutover(db)
        report = generate_historical_dry_run_report(
            db,
            cutover_at=cutover_at,
            output_path=ROOT / "Paper_Trading_Historical_Dry_Run_Report.md",
        )
        print(json.dumps(report, ensure_ascii=False, indent=2))
    finally:
        db.close()


if __name__ == "__main__":
    main()
