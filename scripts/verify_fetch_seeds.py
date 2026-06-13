from __future__ import annotations

import json
import os
import sqlite3
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
TMP = ROOT / "data" / "verify_fetch_seeds"
GOOD_1 = "0x1111111111111111111111111111111111111111"
GOOD_2 = "0x2222222222222222222222222222222222222222"
GOOD_3 = "0x3333333333333333333333333333333333333333"
GOOD_4 = "0x4444444444444444444444444444444444444444"
BAD = "0xBAD"


def main():
    TMP.mkdir(parents=True, exist_ok=True)
    _verify_freedomcore_and_local_write()
    _verify_multi_source_failure_fallback()
    print(json.dumps({"ok": True, "checks": 6}, ensure_ascii=False))


def _verify_freedomcore_and_local_write():
    html_source = TMP / "freedomcore.html"
    local_source = TMP / "seeds.txt"
    output = TMP / "discovery_wallets.txt"
    report = TMP / "fetch_seeds_report.md"
    json_report = TMP / "fetch_seeds_report.json"

    html_source.write_text(
        """
        <table><tbody>
        <tr data-pnl="1200.50" data-roi="0.42" data-wr="0.61" data-trades="88" data-vol="900000">
          <td class="rank-cell">1</td><td>T1</td>
          <td class="addr-cell"><a href="/wallet/0x1111111111111111111111111111111111111111/">0x1111...1111</a></td>
          <td>$1.20K</td><td>42%</td><td>61%</td><td>0.00</td><td>88</td><td>1h</td><td>$900.00K</td><td><span>Trend</span></td>
        </tr>
        <tr data-pnl="500" data-roi="0.12" data-wr="0.55" data-trades="33" data-vol="1000">
          <td class="rank-cell">2</td><td>T3</td>
          <td class="addr-cell"><a href="/wallet/0x2222222222222222222222222222222222222222/">0x2222...2222</a></td>
          <td>$500</td><td>12%</td><td>55%</td><td>0.00</td><td>33</td><td>1h</td><td>$1.00K</td><td><span>Mixed</span></td>
        </tr>
        </tbody></table>
        """,
        encoding="utf-8",
    )
    local_source.write_text("\n".join([GOOD_2, BAD, GOOD_3, GOOD_1, GOOD_4]), encoding="utf-8")

    before_wallet_count = _wallet_count()
    env = _clean_env()
    completed = subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts" / "fetch_seeds.py"),
            "--freedomcore-url",
            html_source.as_uri(),
            "--source-file",
            str(local_source),
            "--skip-top",
            "0",
            "--limit",
            "10",
            "--output",
            str(output),
            "--report",
            str(report),
            "--json-report",
            str(json_report),
        ],
        cwd=ROOT,
        env=env,
        check=False,
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 0, completed.stderr
    payload = json.loads(completed.stdout)
    addresses = output.read_text(encoding="utf-8").splitlines()
    assert addresses == [GOOD_1, GOOD_2, GOOD_3, GOOD_4], addresses
    assert payload["written_count"] == 4, payload
    assert payload["duplicate_count"] >= 2, payload
    assert payload["invalid_count"] >= 1, payload
    assert "NANSEN_API_KEY not configured" in report.read_text(encoding="utf-8")
    assert "APIFY_TOKEN not configured" in report.read_text(encoding="utf-8")
    json_payload = json.loads(json_report.read_text(encoding="utf-8"))
    assert json_payload["records"][0]["pnl_30d"] == 1200.5, json_payload["records"][0]
    assert json_payload["records"][0]["style"] == "Trend", json_payload["records"][0]
    assert before_wallet_count == _wallet_count(), "fetch_seeds.py must not write watchlist/wallets"


def _verify_multi_source_failure_fallback():
    output = TMP / "empty_discovery_wallets.txt"
    report = TMP / "empty_fetch_seeds_report.md"
    json_report = TMP / "empty_fetch_seeds_report.json"
    env = _clean_env()
    completed = subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts" / "fetch_seeds.py"),
            "--freedomcore-url",
            "http://127.0.0.1:1/not-running/",
            "--skip-top",
            "0",
            "--limit",
            "10",
            "--output",
            str(output),
            "--report",
            str(report),
            "--json-report",
            str(json_report),
        ],
        cwd=ROOT,
        env=env,
        check=False,
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 0, completed.stderr
    payload = json.loads(completed.stdout)
    assert payload["written_count"] == 0, payload
    assert "local CSV/TXT" in "\n".join(payload["warnings"]), payload["warnings"]
    assert output.exists()
    assert json_report.exists()


def _clean_env() -> dict:
    env = os.environ.copy()
    env.pop("NANSEN_API_KEY", None)
    env.pop("APIFY_TOKEN", None)
    env["SEED_SOURCE_URLS"] = ""
    return env


def _wallet_count() -> int:
    db_path = ROOT / "apps" / "api" / "data" / "novaion.db"
    if not db_path.exists():
        return 0
    connection = sqlite3.connect(db_path)
    try:
        try:
            return connection.execute("select count(*) from wallets where status != 'deleted'").fetchone()[0]
        except sqlite3.OperationalError:
            return 0
    finally:
        connection.close()


if __name__ == "__main__":
    main()
