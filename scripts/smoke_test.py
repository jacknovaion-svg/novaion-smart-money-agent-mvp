import json
import os
import time
import urllib.error
import urllib.request


BASE_URL = os.environ.get("NOVAION_BASE_URL", "http://127.0.0.1:8000")
EMAIL = os.environ.get("NOVAION_ADMIN_EMAIL", "admin@novaion.ai")
PASSWORD = os.environ.get("NOVAION_ADMIN_PASSWORD", "Novaion@123")


def request(path, *, method="GET", token=None, body=None):
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(
        f"{BASE_URL}{path}",
        data=data,
        headers=headers,
        method=method,
    )
    with urllib.request.urlopen(req, timeout=20) as response:
        if response.status == 204:
            return None
        return json.load(response)


def main():
    health = request("/health")
    assert health["status"] == "ok", health

    token = request(
        "/api/auth/login",
        method="POST",
        body={"email": EMAIL, "password": PASSWORD},
    )["access_token"]

    suffix = f"{int(time.time() * 1000) % 10**8:08x}"
    smoke_address = "0x" + ("0" * 32) + suffix

    wallet = request(
        "/api/wallets",
        method="POST",
        token=token,
        body={
            "address": smoke_address,
            "platform": "hyperliquid",
            "name": "Smoke Test Wallet",
            "tags": "smoke",
            "manual_score": 66,
            "status": "active",
            "notes": "created by scripts/smoke_test.py",
        },
    )

    summary = request("/api/dashboard/summary", token=token)
    assert summary["total_wallets"] >= 1, summary

    market_data = request(f"/api/market-data/wallets/{wallet['id']}", token=token)
    assert "fills" in market_data and "positions" in market_data, market_data

    signals = request("/api/signals", token=token)
    paper = request("/api/signals/paper/summary", token=token)
    trades = request("/api/signals/paper/trades", token=token)
    logs = request("/api/system/logs?limit=5", token=token)

    request(f"/api/wallets/{wallet['id']}", method="DELETE", token=token)

    print(
        json.dumps(
            {
                "ok": True,
                "wallets": summary["total_wallets"],
                "signals": len(signals),
                "paper_equity": paper["current_equity"],
                "paper_trades": len(trades),
                "logs": len(logs),
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    try:
        main()
    except urllib.error.HTTPError as exc:
        payload = exc.read().decode()
        raise SystemExit(f"HTTP {exc.code}: {payload}")
