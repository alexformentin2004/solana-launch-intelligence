"""Persist historical minute OHLCV for a frozen Supabase launch cohort.

Runs in small batches via GitHub Actions; no trades, no public credentials.
"""
import json
import os
import sys
import time
from datetime import datetime, timezone
from urllib.parse import quote
from collector import request_json, db
from historical_candle_audit import API, analyze, fetch_candles, safe_error, timestamp

def rows_for(mint, address, candles, created_at):
    born = timestamp(created_at)
    rows = {}
    for bar in candles:
        try:
            t, op, hi, lo, close, volume = bar[:6]
            t = int(t)
            prices = [float(x) for x in (op, hi, lo, close)]
            if not all(0 < x < float("inf") for x in prices):
                continue
            if prices[1] < max(prices[0], prices[3], prices[2]) or prices[2] > min(prices[0], prices[3]):
                continue
            if not born - 60 <= t <= born + 3600:
                continue
            rows[t] = {
                "mint": mint, "pool_address": address,
                "candle_at": datetime.fromtimestamp(t, timezone.utc).isoformat(),
                "open_usd": str(op), "high_usd": str(hi),
                "low_usd": str(lo), "close_usd": str(close),
                "volume_usd": str(volume) if volume is not None and float(volume) >= 0 else None,
            }
        except (ValueError, TypeError, IndexError):
            continue
    return list(rows.values())

def main():
    url = os.getenv("SUPABASE_URL", "").rstrip("/")
    key = os.getenv("SUPABASE_SERVICE_ROLE_KEY", "")
    if not url or not key:
        print("Missing credentials", file=sys.stderr)
        return 2
    limit = max(1, min(150, int(os.getenv("BACKFILL_BATCH_SIZE", "20"))))
    delay = max(3, float(os.getenv("BACKFILL_DELAY_SECONDS", "5")))
    headers = {"apikey": key, "Authorization": "Bearer " + key}
    endpoint = (url + "/rest/v1/historical_cohort?select=mint,pool_address,created_at"
                + "&order=first_seen_at.asc&limit=1000")
    cohort = request_json(endpoint, headers) or []
    statuses = request_json(url + "/rest/v1/historical_fetch_status?select=mint,status&limit=1000", headers) or []
    done = {r["mint"] for r in statuses if r["status"] != "api_error"}
    pending = [r for r in cohort if r["mint"] not in done][:limit]
    totals = {}
    written = 0
    for launch in pending:
        mint, address = launch["mint"], launch["pool_address"]
        try:
            before = int(timestamp(launch["created_at"]) + 3660)
            endpoint = (API + quote(address, safe="") + "/ohlcv/minute"
                        + "?aggregate=1&limit=120&currency=usd&token=base"
                        + "&before_timestamp=" + str(before))
            payload = fetch_candles(endpoint)
            candles = (((payload.get("data") or {}).get("attributes") or {}).get("ohlcv_list") or [])
            rows = rows_for(mint, address, candles, launch["created_at"])
            if rows:
                db("historical_candles", rows, on_conflict="mint,candle_at")
            result = analyze(launch, candles)
            status = result["status"]
            error = None
            written += len(rows)
        except (OSError, ValueError, KeyError, TypeError) as exc:
            status = "api_error"
            error = safe_error(exc)
            rows = []
        db("historical_fetch_status", [{
            "mint": mint, "attempted_at": datetime.now(timezone.utc).isoformat(),
            "status": status, "candle_count": len(rows), "error_category": error
        }], on_conflict="mint")
        totals[status] = totals.get(status, 0) + 1
        time.sleep(delay)
    print("HISTORICAL_BACKFILL", json.dumps({
        "frozen_cohort_size": len(cohort), "already_processed": len(done),
        "batch_size": len(pending), "candles_written": written,
        "status_counts": totals, "trades": 0
    }, sort_keys=True))
    return 0

if __name__ == "__main__":
    sys.exit(main())
