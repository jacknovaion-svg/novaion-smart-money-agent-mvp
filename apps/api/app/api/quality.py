import json

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.database import get_db
from app.models.signal import DailyReport, SignalPerformance
from app.schemas.auth import CurrentUser
from app.schemas.quality import (
    DailyReportRead,
    QualityDashboardRead,
    RiskRuleRead,
    RiskRuleUpdate,
    SignalPerformanceRead,
    SignalTypeAnalysisRead,
    WalletContributionRead,
)
from app.services.quality_service import (
    generate_daily_report,
    get_or_create_risk_rule,
    quality_dashboard,
    report_to_dict,
    risk_rule_to_dict,
    signal_type_analysis,
    update_signal_performance,
    wallet_contributions,
)


router = APIRouter(prefix="/quality", tags=["quality"])


@router.get("/dashboard", response_model=QualityDashboardRead)
def dashboard(
    db: Session = Depends(get_db),
    _user: CurrentUser = Depends(get_current_user),
) -> dict:
    return quality_dashboard(db)


@router.post("/refresh-performance")
def refresh_performance(
    db: Session = Depends(get_db),
    _user: CurrentUser = Depends(get_current_user),
) -> dict:
    return {"updated": update_signal_performance(db)}


@router.get("/signal-performance", response_model=list[SignalPerformanceRead])
def signal_performance(
    db: Session = Depends(get_db),
    _user: CurrentUser = Depends(get_current_user),
) -> list[SignalPerformance]:
    return db.query(SignalPerformance).order_by(SignalPerformance.last_evaluated_at.desc()).limit(500).all()


@router.get("/wallet-contributions", response_model=list[WalletContributionRead])
def wallet_contribution_rows(
    db: Session = Depends(get_db),
    _user: CurrentUser = Depends(get_current_user),
) -> list[dict]:
    return wallet_contributions(db)


@router.get("/signal-types", response_model=list[SignalTypeAnalysisRead])
def signal_types(
    db: Session = Depends(get_db),
    _user: CurrentUser = Depends(get_current_user),
) -> list[dict]:
    return signal_type_analysis(db)


@router.get("/risk-rules", response_model=RiskRuleRead)
def get_risk_rules(
    db: Session = Depends(get_db),
    _user: CurrentUser = Depends(get_current_user),
) -> dict:
    return risk_rule_to_dict(get_or_create_risk_rule(db))


@router.put("/risk-rules", response_model=RiskRuleRead)
def update_risk_rules(
    payload: RiskRuleUpdate,
    db: Session = Depends(get_db),
    _user: CurrentUser = Depends(get_current_user),
) -> dict:
    rule = get_or_create_risk_rule(db)
    rule.blacklist_wallets = json.dumps(payload.blacklist_wallets, ensure_ascii=False)
    rule.whitelist_wallets = json.dumps(payload.whitelist_wallets, ensure_ascii=False)
    rule.blacklist_symbols = json.dumps(payload.blacklist_symbols, ensure_ascii=False)
    rule.min_wallet_score = payload.min_wallet_score
    rule.max_allowed_leverage = payload.max_allowed_leverage
    rule.min_trades = payload.min_trades
    rule.min_30d_win_rate = payload.min_30d_win_rate
    rule.only_grade_a_or_s = 1 if payload.only_grade_a_or_s else 0
    db.commit()
    db.refresh(rule)
    return risk_rule_to_dict(rule)


@router.post("/daily-report", response_model=DailyReportRead)
def create_daily_report(
    db: Session = Depends(get_db),
    _user: CurrentUser = Depends(get_current_user),
) -> dict:
    return report_to_dict(generate_daily_report(db))


@router.get("/daily-reports", response_model=list[DailyReportRead])
def list_daily_reports(
    db: Session = Depends(get_db),
    _user: CurrentUser = Depends(get_current_user),
) -> list[dict]:
    reports = db.query(DailyReport).order_by(DailyReport.report_date.desc()).limit(30).all()
    return [report_to_dict(report) for report in reports]
