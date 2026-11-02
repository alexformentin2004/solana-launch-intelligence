"""Opt-in persistent Solana pool monitor (paper-data only).

Not started by GitHub Actions. Run on an always-on worker only after checking
API quotas and provisioning SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY privately.
No wallet access, no orders, no performance claims.
"""
import json
import os
import signal
import sys
import time
from datetime import datetime, timezone
from urllib.parse import quote
from collector import API, URL, KEY, db, request_json
from history_worker import pool_address, snapshot

DISCOVERY_SECONDS = max(60, int(os.getenv("MONITOR_DISCOVERY_SECONDS", "120")))
POLL_SECONDS = max(15, int(os.getenv("MONITOR_POLL_SECONDS", "30")))
MAX_ACTIVE = max(1, min(10, int(os.getenv("MONITOR_MAX_ACTIVE", "2"))))
MAX_AGE_SECONDS = max(60, int(os.getenv("MONITOR_MAX_AGE_SECONDS", "900")))
API_ROOT = "https://api.geckoterminal.com/api/v2/networks/solana/pools/"
running = True

def stop(*_args):
    global running
    running = False

def candidate(pool, now):
    attrs = pool.get("attributes") or {}
    token = (((pool.get("relationships") or {}).get("base_token") or {}).get("data") or {}).get("id", "")
    mint = token.removeprefix("solana_")
    address = pool_address({"pool_id": pool.get("id")})
    if not token.startswith("solana_") or not mint or not address:
        return None
    try:
        created = datetime.fromisoformat(str(attrs["pool_created_at"]).replace("Z", "+00:00"))
        age = (now - created).total_seconds()
    except (KeyError, TypeError, ValueError):
        return None
    if not 0 <= age <= MAX_AGE_SECONDS:
        return None
    return mint, address, attrs["pool_created_at"]

def discover(now, active):
    response = request_json(API) or {}
    additions = 0
    for pool in response.get("data") or []:
        parsed = candidate(pool, now)
        if not parsed:
            continue
        mint, address, created = parsed
        if mint in active:
            continue
        if len(active) >= MAX_ACTIVE:
            break
        db("launches", [{"mint": mint, "source": "persistent_geckoterminal",
                         "created_at": created, "first_seen_at": now.isoformat(),
                         "last_seen_at": now.isoformat(),
                         "raw": {"pool_id": pool.get("id"), "pool_name": (pool.get("attributes") or {}).get("name")}}],
           "resolution=ignore-duplicates,return=minimal", "mint")
        active[mint] = {"address": address, "created": created}
        additions += 1
    return additions

def poll(now, active):
    written = 0
    for mint, item in list(active.items()):
        try:
            created = datetime.fromisoformat(str(item["created"]).replace("Z", "+00:00"))
            if (now - created).total_seconds() > MAX_AGE_SECONDS:
                del active[mint]
                continue
            pool = (request_json(API_ROOT + quote(item["address"], safe="")) or {}).get("data")
            if not pool:
                continue
            db("token_snapshots", [snapshot(mint, pool, datetime.now(timezone.utc).isoformat())])
            written += 1
        except (OSError, ValueError, KeyError, TypeError) as exc:
            print("MONITOR_ERROR", mint[:8], type(exc).__name__, str(exc)[:120], flush=True)
    return written

def main():
    if not URL or not KEY:
        print("Missing Supabase secrets", file=sys.stderr)
        return 2
    signal.signal(signal.SIGINT, stop)
    signal.signal(signal.SIGTERM, stop)
    active = {}
    next_discovery = 0.0
    print("MONITOR_START", json.dumps({"discovery_seconds": DISCOVERY_SECONDS,
          "poll_seconds": POLL_SECONDS, "max_active": MAX_ACTIVE,
          "max_age_seconds": MAX_AGE_SECONDS}), flush=True)
    while running:
        now = datetime.now(timezone.utc)
        if time.monotonic() >= next_discovery:
            try:
                added = discover(now, active)
                print("MONITOR_DISCOVER", added, "active", len(active), flush=True)
            except (OSError, ValueError, KeyError, TypeError) as exc:
                print("MONITOR_DISCOVERY_ERROR", type(exc).__name__, str(exc)[:120], flush=True)
            next_discovery = time.monotonic() + DISCOVERY_SECONDS
        count = poll(datetime.now(timezone.utc), active)
        print("MONITOR_POLL", "written", count, "active", len(active), flush=True)
        end = time.monotonic() + POLL_SECONDS
        while running and time.monotonic() < end:
            time.sleep(min(1, end - time.monotonic()))
    print("MONITOR_STOP", flush=True)
    return 0

if __name__ == "__main__":
    sys.exit(main())
