import time
from typing import Any, Dict

import httpx
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.services.system_log_service import write_log
from app.services.ops_service import record_hyperliquid_metric


class HyperliquidApiClient:
    def __init__(self, db: Session):
        self.db = db
        self.settings = get_settings()
        self.base_url = self.settings.hyperliquid_api_base_url.rstrip("/")
        self._last_request_at = 0.0

    def post_info(self, payload: Dict[str, Any], *, weight: int = 20) -> Any:
        self._rate_limit(weight)
        request_type = payload.get("type", "unknown")
        last_error = ""
        for attempt in range(1, 4):
            started = time.monotonic()
            try:
                with httpx.Client(timeout=15) as client:
                    response = client.post(
                        f"{self.base_url}/info",
                        json=payload,
                        headers={"Content-Type": "application/json"},
                    )
                    response.raise_for_status()
                    data = response.json()
                record_hyperliquid_metric(self.db, success=True, latency_ms=(time.monotonic() - started) * 1000)
                write_log(
                    self.db,
                    level="info",
                    module="hyperliquid",
                    message="Info request succeeded",
                    payload={"type": request_type, "attempt": attempt},
                )
                return data
            except Exception as exc:
                last_error = str(exc)
                record_hyperliquid_metric(
                    self.db,
                    success=False,
                    latency_ms=(time.monotonic() - started) * 1000,
                    error=last_error,
                )
                write_log(
                    self.db,
                    level="warning",
                    module="hyperliquid",
                    message="Info request failed",
                    payload={"type": request_type, "attempt": attempt, "error": last_error},
                )
                time.sleep(min(2**attempt, 8))
        write_log(
            self.db,
            level="error",
            module="hyperliquid",
            message="Info request exhausted retries",
            payload={"type": request_type, "error": last_error},
        )
        raise RuntimeError(f"Hyperliquid request failed: {last_error}")

    def get_all_mids(self) -> Dict[str, str]:
        return self.post_info({"type": "allMids"}, weight=2)

    def get_open_orders(self, user: str) -> list[Dict[str, Any]]:
        return self.post_info({"type": "openOrders", "user": user}, weight=20)

    def get_user_fills(self, user: str) -> list[Dict[str, Any]]:
        return self.post_info({"type": "userFills", "user": user}, weight=20)

    def get_clearinghouse_state(self, user: str) -> Dict[str, Any]:
        return self.post_info({"type": "clearinghouseState", "user": user}, weight=2)

    def get_user_fills_by_time(self, user: str, start_time_ms: int, end_time_ms: int) -> list[Dict[str, Any]]:
        return self.post_info(
            {
                "type": "userFillsByTime",
                "user": user,
                "startTime": start_time_ms,
                "endTime": end_time_ms,
                "aggregateByTime": True,
            },
            weight=20,
        )

    def _rate_limit(self, weight: int) -> None:
        # Keep a conservative pace for the MVP. Hyperliquid has weighted limits; this protects small tests.
        min_delay = max(0.15, weight * 0.015)
        elapsed = time.monotonic() - self._last_request_at
        if elapsed < min_delay:
            time.sleep(min_delay - elapsed)
        self._last_request_at = time.monotonic()
