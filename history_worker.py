"""Refresh historical price/liquidity snapshots for recently discovered Solana pools.

Free-tier friendly: at most 10 GeckoTerminal pool requests per execution.
Historical snapshots are observations, not executable quotes.
"""
import os
import sys
import time
from datetime import datetime, timezone
from urllib.parse import quote
from collector import db, request_json, URL, KEY

MAX_POOLS = 10
API_ROOT = "https://api.geckoterminal.com/api/v2/networks/solana/pools/"

def pool_address(raw):
    pool_id = (raw or {}).get("pool_id") or ""
    if not pool_id.startswith("solana_"):
        return None
    address = pool_id[len("solana_"):]
    return address if 32 <= len(address) <= 64 else None

def snapshot(mint, pool, observed_at):
    attrs = pool.get("attributes") or {}
    tx = ((attrs.get("transactions") or {}).get("m5") or {})
    return {
        "mint": mint, "observed_at": observed_at,
        "price_usd": attrs.get("base_token_price_usd"),
        "liquidity_usd": attrs.get("reserve_in_usd"),
        "volume_5m_usd": (attrs.get("volume_usd") or {}).get("m5"),
        "buys_5m": tx.get("buys"), "sells_5m": tx.get("sells"),
        "raw": {"pool_id": pool.get("id"), "source": "geckoterminal_pool_refresh"},
    }

def main():
    if not URL or not KEY:
        print("Missing Supabase configuration", file=sys.stderr)
        return 2
    from collector import request_json as fetch
    headers = {"apikey": KEY, "Authorization": "Bearer " + KEY}
    # Revisit the newest launches; preserve snapshots across runs, including failed tokens.
    query = (URL + "/rest/v1/launches?select=mint,raw,first_seen_at"
             "&order=first_seen_at.desc&limit=100")
    launches = fetch(query, headers=headers) or []
    observed_at = datetime.now(timezone.utc).isoformat()
    written = 0
    failed = 0
    # Rotate across recent launches instead of polling the same ten forever.
    # A 5-minute schedule advances one batch per execution.
    slot = int(datetime.now(timezone.utc).timestamp() // 300)
    if launches:
        start = (slot * MAX_POOLS) % len(launches)
        launches = launches[start:] + launches[:start]
    for launch in launches:
        if written + failed >= MAX_POOLS:
            break
        address = pool_address(launch.get("raw"))
        if not address:
            continue
        try:
            result = fetch(API_ROOT + quote(address, safe=""))
            pool = (result or {}).get("data") or {}
            if not pool:
                failed += 1
                continue
            db("token_snapshots", [snapshot(launch["mint"], pool, observed_at)])
            written += 1
        except (OSError, ValueError, KeyError, TypeError) as exc:
            failed += 1
            print("HISTORY refresh_failed", launch["mint"][:8], type(exc).__name__, flush=True)
        time.sleep(0.15)
    print("HISTORY refreshed", written, "failed", failed, "limit", MAX_POOLS, flush=True)
    return 0 if written or not launches else 1

if __name__ == "__main__":
    sys.exit(main())
