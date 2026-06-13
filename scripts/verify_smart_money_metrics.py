import json
import os
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "apps" / "api"))


def main():
    os.environ.setdefault("DATABASE_URL", "sqlite:///./data/novaion_smart_metrics_verify.db")
    os.environ["SMART_MIN_TRADE_COUNT_30D"] = "30"
    os.environ["SMART_MIN_WIN_RATE"] = "0.55"
    os.environ["SMART_MIN_PROFIT_FACTOR"] = "1.2"
    os.environ["SMART_MAX_SINGLE_LOSS_PCT"] = "0.30"
    os.environ["SMART_SOFT_WATCH_MIN_GROSS_PROFIT"] = "1000"
    os.environ["SMART_SOFT_WATCH_MIN_TRADE_COUNT_30D"] = "20"

    from app.core.config import get_settings
    from app.services.discovery_service import _score_candidate

    get_settings.cache_clear()
    soft = _score_candidate("0x1111111111111111111111111111111111111111", _fills(wins=24, losses=1), _state(), [])
    assert soft["aggregation_confidence"] == "low", soft
    assert soft["soft_watch_eligible"] == 1, soft
    assert soft["grade"] in {"B", "Watch"}, soft
    assert soft["recommendation"] == "watch", soft
    assert soft["score"] < 85, soft

    assert soft["recommendation"] != "recommend_add", soft
    assert soft["score"] < 85, soft

    os.environ["SMART_MIN_TRADE_COUNT_30D"] = "90"
    get_settings.cache_clear()
    stricter = _score_candidate("0x2222222222222222222222222222222222222222", _fills(wins=80, losses=5), _state(), [])
    assert stricter["hard_filter_pass"] == 0, stricter
    assert "trade_count_30d_below_threshold" in json.loads(stricter["failed_reasons"]), stricter

    os.environ["SMART_MIN_TRADE_COUNT_30D"] = "30"
    get_settings.cache_clear()
    hard = _score_candidate("0x3333333333333333333333333333333333333333", _fills(wins=35, losses=3), _state(), [])
    assert hard["hard_filter_pass"] == 1, hard

    print(json.dumps({"ok": True, "soft": _summary(soft), "stricter": _summary(stricter), "hard": _summary(hard)}, ensure_ascii=False))


def _fills(wins: int, losses: int):
    rows = []
    now_ms = 1_800_000_000_000
    for idx in range(wins):
        rows.append({"coin": "BTC", "closedPnl": "60", "time": now_ms - idx * 60_000})
    for idx in range(losses):
        rows.append({"coin": "ETH", "closedPnl": "-20", "time": now_ms - (idx + wins) * 60_000})
    return rows


def _state():
    return {"marginSummary": {"accountValue": "5000"}, "assetPositions": []}


def _summary(metrics):
    return {
        "score": metrics["score"],
        "grade": metrics["grade"],
        "recommendation": metrics["recommendation"],
        "hard_filter_pass": metrics["hard_filter_pass"],
        "soft_watch_eligible": metrics["soft_watch_eligible"],
        "failed_reasons": json.loads(metrics["failed_reasons"]),
    }


if __name__ == "__main__":
    main()
