"""Historical 1-minute candle coverage audit. Read-only; no trading.

Usage: SUPABASE_URL=... SUPABASE_SERVICE_ROLE_KEY=... python historical_candle_audit.py
Optional: HISTORICAL_MAX_POOLS=40, HISTORICAL_OFFSET=0, HISTORICAL_DELAY_SECONDS=5.
"""
import json
import re
import os
import sys
import time
from datetime import datetime, timezone
import urllib.error
from urllib.parse import quote
from collector import request_json
from history_worker import pool_address

API = "https://api.geckoterminal.com/api/v2/networks/solana/pools/"
def timestamp(value):
    return datetime.fromisoformat(str(value).replace("Z", "+00:00")).timestamp()

def analyze(launch, candles):
    """Classify minute candles without pretending intraminute execution is known."""
    try:
        born = timestamp(launch["created_at"])
    except (KeyError, TypeError, ValueError):
        return {"status": "unknown_creation"}
    valid = {}
    for candle in candles:
        try:
            t, op, high, low, close, volume = candle[:6]
            t = int(t)
            prices = [float(x) for x in (op, high, low, close)]
            if min(prices) <= 0 or prices[2] > min(prices) or prices[1] < max(prices):
                continue
            if born - 60 <= t <= born + 3600:
                valid[t] = prices
        except (TypeError, ValueError, IndexError):
            continue
    bars = sorted(valid)
    # Minute candles cannot establish an executable quote at a precise 30-90s entry.
    entry_bars = [t for t in bars if t <= born + 90 and t + 60 >= born + 30]
    if not entry_bars:
        return {"status": "no_entry_overlap", "minute_bars": len(bars)}
    entry_t = entry_bars[0]
    after = [t for t in bars if t > entry_t]
    if not after:
        return {"status": "entry_bar_only", "minute_bars": len(bars)}
    gaps = [b-a for a,b in zip([entry_t]+after, after)]
    return {"status": "exploratory_candles" if max(gaps) <= 60 else "gapped_candles",
            "minute_bars": len(bars), "entry_bar_start": entry_t,
            "max_gap_seconds": max(gaps),
            "entry_open_usd": valid[entry_t][0],
            "last_close_usd": valid[after[-1]][3],
            "note": "No 30-90s executable entry or TP/SL order can be established from OHLC."}

def safe_error(exc):
    """Return actionable HTTP diagnostics without leaking URLs or credentials."""
    message = str(exc)
    match = re.search(r"HTTP (\d{3})", message)
    if match:
        code = int(match.group(1))
        return ("rate_limited" if code == 429 else
                "not_found" if code == 404 else
                "api_http_" + str(code))
    if isinstance(exc, ValueError):
        return "invalid_response_or_timestamp"
    return type(exc).__name__

def fetch_candles(endpoint, tries=4):
    """Retry only HTTP 429 with bounded backoff; never return fabricated candles."""
    for attempt in range(tries):
        try:
            return request_json(endpoint) or {}
        except ValueError as exc:
            if safe_error(exc) != "rate_limited" or attempt == tries - 1:
                raise
            time.sleep(min(60, 8 * (attempt + 1)))

def main():
    url = os.getenv("SUPABASE_URL", "").rstrip("/")
    key = os.getenv("SUPABASE_SERVICE_ROLE_KEY", "")
    if not url or not key:
        print("Missing Supabase credentials", file=sys.stderr)
        return 2
    max_pools = max(1, min(60, int(os.getenv("HISTORICAL_MAX_POOLS", "40"))))
    offset = max(0, int(os.getenv("HISTORICAL_OFFSET", "0")))
    delay = max(2.1, float(os.getenv("HISTORICAL_DELAY_SECONDS", "5")))
    headers = {"apikey": key, "Authorization": "Bearer " + key}
    launches = request_json(url + "/rest/v1/launches?select=mint,created_at,raw"
                            "&order=first_seen_at.desc&limit=" + str(max_pools)
                            + "&offset=" + str(offset), headers) or []
    summary = {}
    error_categories = {}
    results = []
    for launch in launches:
        address = pool_address(launch.get("raw"))
        if not address:
            status = "missing_pool_address"
            result = {"status": status}
        else:
            try:
                # Fetch candles up to 1h after launch, rather than only the latest bars.
                before = int(timestamp(launch["created_at"]) + 3660)
                endpoint = (API + quote(address, safe="") + "/ohlcv/minute"
                            + "?aggregate=1&limit=120&currency=usd&token=base"
                            + "&before_timestamp=" + str(before))
                response = fetch_candles(endpoint)
                candles = (((response.get("data") or {}).get("attributes") or {})
                           .get("ohlcv_list") or [])
                result = analyze(launch, candles)
            except (OSError, ValueError, TypeError, KeyError) as exc:
                result = {"status": "api_error", "error_type": safe_error(exc)}
        status = result["status"]
        summary[status] = summary.get(status, 0) + 1
        if status == "api_error":
            category = result["error_type"]
            error_categories[category] = error_categories.get(category, 0) + 1
        results.append({"mint_prefix": launch["mint"][:8], **result})
        time.sleep(delay)
    print("HISTORICAL_CANDLE_AUDIT", json.dumps({
        "pools_checked": len(launches), "offset": offset,
        "classification": summary,
        "error_categories": error_categories,
        "results": results,
        "roi_pct": None,
        "warning": "OHLC minute candles are not executable prices; no ROI calculated."
    }, sort_keys=True))
    return 0

if __name__ == "__main__":
    sys.exit(main())
