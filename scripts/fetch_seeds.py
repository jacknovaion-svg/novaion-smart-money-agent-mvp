#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import html
import json
import os
import re
import sys
from pathlib import Path
from urllib.parse import urljoin
from urllib.request import Request, urlopen


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = ROOT / "apps" / "api" / "data" / "discovery_wallets.txt"
DEFAULT_REPORT = ROOT / "fetch_seeds_report.md"
DEFAULT_JSON_REPORT = ROOT / "fetch_seeds_report.json"
FREEDOMCORE_URL = "https://arena.freedomcore.io/"
NANSEN_URL = "https://api.nansen.ai/api/v1/perp-leaderboard"
APIFY_ACTOR_ID = "saswave/hyperliquid-leaderboard-vaults-scraper"
ADDRESS_RE = re.compile(r"^0x[a-fA-F0-9]{40}$")
ADDRESS_SCAN_RE = re.compile(r"0x[a-fA-F0-9]{40}")


def main():
    args = _parse_args()
    warnings: list[str] = []
    source_results: list[dict] = []

    source_results.append(_fetch_freedomcore(args.freedomcore_url, warnings))
    source_results.append(_fetch_nansen(args.nansen_url, os.getenv("NANSEN_API_KEY", ""), warnings))
    source_results.append(_fetch_apify(os.getenv("APIFY_TOKEN", ""), warnings))

    for url in _split_sources(args.source_url) + _split_sources(os.getenv("SEED_SOURCE_URLS", "")):
        source_results.append(_fetch_generic_url(url, warnings))

    for file_path in args.source_file:
        source_results.append(_read_file(Path(file_path), warnings))

    all_records = [record for result in source_results for record in result["records"]]
    invalid_count = sum(result["invalid_count"] for result in source_results)
    ranked = _dedupe_records(all_records)
    selected = ranked[args.skip_top : args.skip_top + args.limit]

    if not selected:
        warnings.append("No seed wallets were written. Use apps/api/data/seeds.txt or --source-file with a local CSV/TXT export.")

    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text("\n".join(item["address"] for item in selected) + ("\n" if selected else ""), encoding="utf-8")

    report = {
        "found_count": len(all_records),
        "valid_count": len(all_records),
        "invalid_count": invalid_count,
        "duplicate_count": max(len(all_records) - len(ranked), 0),
        "inserted_count": len(selected),
        "source": ", ".join(result["name"] for result in source_results),
        "total_raw_addresses": len(all_records),
        "unique_addresses": len(ranked),
        "skip_top": args.skip_top,
        "limit": args.limit,
        "written_count": len(selected),
        "output": str(output),
        "sources": [
            {
                "name": item["name"],
                "status": item["status"],
                "address_count": len(item["records"]),
                "warnings": item["warnings"],
            }
            for item in source_results
        ],
        "records": selected,
        "warnings": warnings,
    }
    _write_report(Path(args.report), report)
    _write_json_report(Path(args.json_report), report)
    print(json.dumps(report, ensure_ascii=False))


def _parse_args():
    parser = argparse.ArgumentParser(description="Fetch Hyperliquid seed wallets for NOVAION Discovery.")
    parser.add_argument("--skip-top", type=int, default=int(os.getenv("SEED_SKIP_TOP", "50")))
    parser.add_argument("--limit", type=int, default=int(os.getenv("SEED_FETCH_LIMIT", "200")))
    parser.add_argument("--output", default=os.getenv("SEED_OUTPUT_PATH", str(DEFAULT_OUTPUT)))
    parser.add_argument("--report", default=os.getenv("SEED_REPORT_PATH", str(DEFAULT_REPORT)))
    parser.add_argument("--json-report", default=os.getenv("SEED_JSON_REPORT_PATH", str(DEFAULT_JSON_REPORT)))
    parser.add_argument("--source-url", action="append", default=[], help="Third-party CSV/TXT/JSON URL. Can be repeated or comma-separated.")
    parser.add_argument("--source-file", action="append", default=[], help="Local CSV/TXT file. Can be repeated.")
    parser.add_argument("--freedomcore-url", default=os.getenv("FREEDOMCORE_ARENA_URL", FREEDOMCORE_URL))
    parser.add_argument("--nansen-url", default=os.getenv("NANSEN_HYPERLIQUID_LEADERBOARD_URL", NANSEN_URL))
    return parser.parse_args()


def _fetch_freedomcore(base_url: str, warnings: list[str]) -> dict:
    local_warnings: list[str] = []
    urls = [
        base_url,
        urljoin(base_url, "/tier/t1/"),
        urljoin(base_url, "/tier/t2/"),
        urljoin(base_url, "/tier/t3/"),
    ]
    records: list[dict] = []
    invalid_count = 0
    for url in urls:
        try:
            content = _http_request(url)
            records.extend(_parse_freedomcore_html(content, url))
            invalid_count += len(_invalid_address_tokens(content))
        except Exception as exc:
            message = f"FreedomCore source failed: {url}: {exc}"
            local_warnings.append(message)
            warnings.append(message)
    if not records:
        message = "FreedomCore Arena returned no full wallet addresses; fallback to Nansen, Apify, or local CSV/TXT."
        local_warnings.append(message)
        warnings.append(message)
    return _source_result("freedomcore_arena", "ok" if records else "failed", records, invalid_count, local_warnings)


def _parse_freedomcore_html(content: str, source: str) -> list[dict]:
    records: list[dict] = []
    rows = re.findall(r"<tr\b(?P<attrs>[^>]*)>(?P<body>.*?)</tr>", content, flags=re.IGNORECASE | re.DOTALL)
    for attrs, body in rows:
        address_match = re.search(r"/wallet/(0x[a-fA-F0-9]{40})/?", body)
        if not address_match:
            continue
        cells = re.findall(r"<td[^>]*>(.*?)</td>", body, flags=re.IGNORECASE | re.DOTALL)
        rank = _clean_html(cells[0]) if cells else ""
        style = _clean_html(cells[-1]) if cells else ""
        records.append(
            _record(
                source="freedomcore_arena",
                address=address_match.group(1),
                rank=_int_or_none(rank),
                pnl_30d=_float_attr(attrs, "data-pnl"),
                roi_30d=_float_attr(attrs, "data-roi"),
                win_rate=_float_attr(attrs, "data-wr"),
                trades=_int_attr(attrs, "data-trades"),
                volume=_float_attr(attrs, "data-vol"),
                style=style,
            )
        )

    if records:
        return records

    for position, address in enumerate(ADDRESS_SCAN_RE.findall(content), start=1):
        records.append(_record(source="freedomcore_arena", address=address, rank=position))
    return records


def _fetch_nansen(url: str, api_key: str, warnings: list[str]) -> dict:
    if not api_key:
        message = "NANSEN_API_KEY not configured; Nansen adapter skipped."
        warnings.append(message)
        return _source_result("nansen", "skipped", [], 0, [message])
    try:
        payload = {"page": 1, "per_page": 250, "chain": "hyperliquid"}
        content = _http_request(url, method="POST", headers={"apiKey": api_key, "X-API-Key": api_key}, body=json.dumps(payload))
        records = _parse_nansen_json(content)
        return _source_result("nansen", "ok" if records else "empty", records, len(_invalid_address_tokens(content)), [])
    except Exception as exc:
        message = f"Nansen adapter failed: {exc}"
        warnings.append(message)
        return _source_result("nansen", "failed", [], 0, [message])


def _parse_nansen_json(content: str) -> list[dict]:
    payload = json.loads(content)
    rows = _find_rows(payload)
    records = []
    for index, row in enumerate(rows, start=1):
        address = _pick(row, "trader_address", "address", "wallet_address")
        if not address:
            continue
        records.append(
            _record(
                source="nansen",
                address=address,
                rank=_int_or_none(_pick(row, "rank")) or index,
                pnl_30d=_float_or_none(_pick(row, "total_pnl", "pnl_30d", "realized_pnl")),
                roi_30d=_float_or_none(_pick(row, "roi", "roi_30d")),
                account_value=_float_or_none(_pick(row, "account_value")),
            )
        )
    return records


def _fetch_apify(api_token: str, warnings: list[str]) -> dict:
    if not api_token:
        message = "APIFY_TOKEN not configured; Apify adapter skipped."
        warnings.append(message)
        return _source_result("apify", "skipped", [], 0, [message])
    actor_id = os.getenv("APIFY_HYPERLIQUID_ACTOR_ID", APIFY_ACTOR_ID).replace("/", "~")
    url = f"https://api.apify.com/v2/acts/{actor_id}/run-sync-get-dataset-items?token={api_token}&clean=true&format=json"
    try:
        content = _http_request(url, method="POST", body=json.dumps({"limit": 250}))
        records = _parse_apify_json(content)
        return _source_result("apify", "ok" if records else "empty", records, len(_invalid_address_tokens(content)), [])
    except Exception as exc:
        message = f"Apify adapter failed: {exc}"
        warnings.append(message)
        return _source_result("apify", "failed", [], 0, [message])


def _parse_apify_json(content: str) -> list[dict]:
    payload = json.loads(content)
    rows = _find_rows(payload)
    records = []
    for index, row in enumerate(rows, start=1):
        address = _pick(row, "ethAddress", "eth_address", "address", "wallet")
        if not address:
            continue
        records.append(
            _record(
                source="apify",
                address=address,
                rank=_int_or_none(_pick(row, "rank")) or index,
                pnl_30d=_float_or_none(_pick(row, "monthlyPnl", "monthPnl", "pnl30d", "pnl_30d")),
                roi_30d=_float_or_none(_pick(row, "monthlyRoi", "monthRoi", "roi30d", "roi_30d")),
                volume=_float_or_none(_pick(row, "monthlyVolume", "monthVolume", "volume")),
                account_value=_float_or_none(_pick(row, "accountValue", "account value", "account_value")),
            )
        )
    return records


def _fetch_generic_url(url: str, warnings: list[str]) -> dict:
    try:
        content = _http_request(url)
        records = _parse_generic_content(content, url)
        return _source_result(url, "ok" if records else "empty", records, len(_invalid_address_tokens(content)), [])
    except Exception as exc:
        message = f"Third-party source failed: {url}: {exc}"
        warnings.append(message)
        return _source_result(url, "failed", [], 0, [message])


def _read_file(path: Path, warnings: list[str]) -> dict:
    try:
        content = path.read_text(encoding="utf-8")
        records = _parse_generic_content(content, str(path))
        return _source_result(str(path), "ok" if records else "empty", records, len(_invalid_address_tokens(content)), [])
    except Exception as exc:
        message = f"Local source failed: {path}: {exc}"
        warnings.append(message)
        return _source_result(str(path), "failed", [], 0, [message])


def _parse_generic_content(content: str, source: str) -> list[dict]:
    if not content:
        return []
    try:
        payload = json.loads(content)
        rows = _find_rows(payload)
        records = []
        for index, row in enumerate(rows, start=1):
            address = _pick(row, "address", "wallet", "wallet_address", "trader_address", "ethAddress")
            if address:
                records.append(_record(source=source, address=address, rank=_int_or_none(_pick(row, "rank")) or index))
        if records:
            return records
    except json.JSONDecodeError:
        pass

    records = []
    for index, address in enumerate(ADDRESS_SCAN_RE.findall(content), start=1):
        records.append(_record(source=source, address=address, rank=index))
    if records:
        return records

    try:
        for index, row in enumerate(csv.DictReader(content.splitlines()), start=1):
            address = _pick(row, "address", "wallet", "wallet_address", "trader_address", "ethAddress")
            if address:
                records.append(_record(source=source, address=address, rank=_int_or_none(_pick(row, "rank")) or index))
    except csv.Error:
        return records
    return records


def _http_request(url: str, method: str = "GET", headers: dict | None = None, body: str | None = None) -> str:
    base_headers = {"User-Agent": "NOVAION-SeedSourceEngine/1.1", "Accept": "application/json,text/html,*/*"}
    if body:
        base_headers["Content-Type"] = "application/json"
    req = Request(url, data=body.encode("utf-8") if body else None, headers={**base_headers, **(headers or {})}, method=method)
    with urlopen(req, timeout=30) as response:
        return response.read().decode("utf-8", errors="replace")


def _record(
    source: str,
    address: str,
    rank: int | None = None,
    pnl_30d: float | None = None,
    roi_30d: float | None = None,
    win_rate: float | None = None,
    trades: int | None = None,
    volume: float | None = None,
    account_value: float | None = None,
    style: str | None = None,
    warnings: list[str] | None = None,
) -> dict:
    return {
        "source": source,
        "rank": rank,
        "address": address.lower(),
        "pnl_30d": pnl_30d,
        "roi_30d": roi_30d,
        "win_rate": win_rate,
        "trades": trades,
        "volume": volume,
        "account_value": account_value,
        "style": style,
        "warnings": warnings or [],
    }


def _source_result(name: str, status: str, records: list[dict], invalid_count: int, warnings: list[str]) -> dict:
    valid_records = [record for record in records if ADDRESS_RE.match(record.get("address", ""))]
    invalid_from_records = len(records) - len(valid_records)
    return {
        "name": name,
        "status": status,
        "records": valid_records,
        "invalid_count": invalid_count + invalid_from_records,
        "warnings": warnings,
    }


def _dedupe_records(items: list[dict]) -> list[dict]:
    seen = set()
    result = []
    for item in items:
        address = item["address"].lower()
        if address in seen:
            continue
        seen.add(address)
        normalized = dict(item)
        normalized["address"] = address
        result.append(normalized)
    return result


def _find_rows(payload) -> list[dict]:
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    if isinstance(payload, dict):
        for key in ("data", "items", "rows", "result", "results", "leaderboard"):
            rows = payload.get(key)
            if isinstance(rows, list):
                return [item for item in rows if isinstance(item, dict)]
            if isinstance(rows, dict):
                nested = _find_rows(rows)
                if nested:
                    return nested
    return []


def _pick(row: dict, *keys: str):
    for key in keys:
        if key in row and row[key] not in (None, ""):
            return row[key]
    lowered = {str(key).lower(): value for key, value in row.items()}
    for key in keys:
        value = lowered.get(key.lower())
        if value not in (None, ""):
            return value
    return None


def _float_attr(attrs: str, name: str) -> float | None:
    match = re.search(rf'{re.escape(name)}="([^"]+)"', attrs)
    return _float_or_none(match.group(1) if match else None)


def _int_attr(attrs: str, name: str) -> int | None:
    match = re.search(rf'{re.escape(name)}="([^"]+)"', attrs)
    return _int_or_none(match.group(1) if match else None)


def _float_or_none(value) -> float | None:
    if value is None:
        return None
    cleaned = str(value).replace("$", "").replace(",", "").replace("%", "").strip()
    multiplier = 1.0
    if cleaned.lower().endswith("k"):
        multiplier = 1_000.0
        cleaned = cleaned[:-1]
    elif cleaned.lower().endswith("m"):
        multiplier = 1_000_000.0
        cleaned = cleaned[:-1]
    try:
        return float(cleaned) * multiplier
    except ValueError:
        return None


def _int_or_none(value) -> int | None:
    parsed = _float_or_none(value)
    return int(parsed) if parsed is not None else None


def _clean_html(value: str) -> str:
    return html.unescape(re.sub(r"<[^>]+>", "", value)).strip()


def _invalid_address_tokens(content: str) -> list[str]:
    return [token for token in re.findall(r"0x[0-9a-zA-Z]+", content or "") if not ADDRESS_RE.match(token)]


def _split_sources(values) -> list[str]:
    result = []
    for item in values if isinstance(values, list) else [values]:
        result.extend(part.strip() for part in str(item or "").split(",") if part.strip())
    return result


def _write_report(path: Path, report: dict) -> None:
    lines = [
        "# Seed Source Engine Report",
        "",
        "## Audit",
        "",
        f"- found_count: {report['found_count']}",
        f"- valid_count: {report['valid_count']}",
        f"- invalid_count: {report['invalid_count']}",
        f"- duplicate_count: {report['duplicate_count']}",
        f"- inserted_count: {report['inserted_count']}",
        f"- source: `{report['source']}`",
        "",
        f"- Total raw addresses: {report['total_raw_addresses']}",
        f"- Unique addresses: {report['unique_addresses']}",
        f"- Skip top: {report['skip_top']}",
        f"- Limit: {report['limit']}",
        f"- Written count: {report['written_count']}",
        f"- Output: `{report['output']}`",
        "",
        "## Sources",
        "",
    ]
    for source in report["sources"]:
        lines.append(f"- `{source['name']}`: {source['status']}, addresses={source['address_count']}")
        for warning in source["warnings"]:
            lines.append(f"  - warning: {warning}")
    lines.extend(["", "## Selected Records", ""])
    lines.append("| source | rank | address | pnl_30d | roi_30d | win_rate | trades | volume | account_value | warnings |")
    lines.append("|---|---:|---|---:|---:|---:|---:|---:|---:|---|")
    for record in report["records"][:250]:
        lines.append(
            "| {source} | {rank} | `{address}` | {pnl_30d} | {roi_30d} | {win_rate} | {trades} | {volume} | {account_value} | {warnings} |".format(
                source=record.get("source") or "",
                rank=record.get("rank") or "",
                address=record.get("address") or "",
                pnl_30d=_display(record.get("pnl_30d")),
                roi_30d=_display(record.get("roi_30d")),
                win_rate=_display(record.get("win_rate")),
                trades=_display(record.get("trades")),
                volume=_display(record.get("volume")),
                account_value=_display(record.get("account_value")),
                warnings=", ".join(record.get("warnings") or []),
            )
        )
    lines.extend(["", "## Warnings", ""])
    lines.extend(f"- {warning}" for warning in report["warnings"])
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _write_json_report(path: Path, report: dict) -> None:
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _display(value) -> str:
    return "" if value is None else str(value)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        sys.exit(130)
