"""Bounded RPC audit queue. Existing token_audits rows are the durable queue."""
import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from onchain import mint_checks
from concentration import concentration, RPCMethodError
from auditor import audit

URL = os.environ.get("SUPABASE_URL", "").rstrip("/")
KEY = os.environ.get("SUPABASE_SERVICE_ROLE_KEY", "")
LIMIT = 1
RETRY_MINUTES = 60
MAX_ATTEMPTS = 5
PERMANENT_ERRORS = {"unsupported_program", "unavailable"}

def db(method, path, data=None):
    headers = {"apikey": KEY, "Authorization": "Bearer " + KEY,
               "Content-Type": "application/json", "Accept": "application/json",
               "Prefer": "return=minimal"}
    payload = json.dumps(data).encode() if data is not None else None
    request = urllib.request.Request(URL + "/rest/v1/" + path, data=payload,
                                     headers=headers, method=method)
    with urllib.request.urlopen(request, timeout=20) as response:
        return json.load(response) if method == "GET" else None

def eligible(row, now=None):
    now = now or datetime.now(timezone.utc)
    metrics = row.get("metrics") or {}
    queue = metrics.get("rpc_queue") or {}
    if int(queue.get("attempts") or 0) >= MAX_ATTEMPTS:
        return False
    next_at = queue.get("next_attempt_at")
    if next_at:
        try:
            if datetime.fromisoformat(next_at.replace("Z", "+00:00")) > now:
                return False
        except ValueError:
            pass
    chain = metrics.get("onchain") or {}
    holders = metrics.get("concentration") or {}
    if chain.get("status") in PERMANENT_ERRORS:
        return False
    return chain.get("status") != "verified" or holders.get("status") not in ("verified", "unavailable")

def priority(row):
    metrics = row.get("metrics") or {}
    liquidity = max(0, float(metrics.get("liquidity_usd") or 0))
    volume = max(0, float(metrics.get("volume_5m_usd") or 0))
    # Bounded liquidity/volume weighting prevents huge outliers dominating.
    import math
    score = min(5, math.log10(1 + liquidity)) + min(5, math.log10(1 + volume))
    if (metrics.get("onchain") or {}).get("status") == "verified":
        score += 2  # finish partially verified audits before starting new RPC work
    return score

def candidates():
    # Scan newest audit rows first, but process only audits whose cooldown expired.
    path = "token_audits?select=mint,metrics,audited_at&order=audited_at.desc&limit=500"
    rows = db("GET", path)
    now = datetime.now(timezone.utc)
    return sorted((r for r in rows if eligible(r, now)), key=priority, reverse=True)

def process(row):
    mint = row["mint"]
    old = row.get("metrics") or {}
    chain = old.get("onchain") or {"status":"not_checked"}
    holders = old.get("concentration") or {"status":"not_checked"}
    throttled = False
    previous = (old.get("rpc_queue") or {})
    attempts = int(previous.get("attempts") or 0) + 1
    if chain.get("status") != "verified":
        try:
            chain = mint_checks(mint)
        except (OSError, ValueError, KeyError, TypeError) as exc:
            throttled = getattr(exc, "code", None) == 429
            chain = {"status":"error","error_type":type(exc).__name__,
                     "error_detail":str(exc)[:150]}
    if chain.get("status") == "verified" and holders.get("status") != "verified" and not throttled:
        time.sleep(2)
        try:
            holders = concentration(mint)
        except RPCMethodError as exc:
            throttled = exc.kind == "rate_limited"
            holders = {"status":"error","failed_method":exc.method,
                       "error_kind":exc.kind,"error_detail":exc.detail,
                       "retryable":exc.retryable}
        except (OSError, ValueError, KeyError, TypeError) as exc:
            throttled = getattr(exc, "code", None) == 429
            holders = {"status":"error","error_type":type(exc).__name__,
                       "error_detail":str(exc)[:150]}
    pool = {"attributes":{"reserve_in_usd":old.get("liquidity_usd"),
                          "volume_usd":{"m5":old.get("volume_5m_usd")},
                          "transactions":{"m5":{"buys":old.get("buys_5m"),
                                                 "sells":old.get("sells_5m")}},
                          "pool_created_at":old.get("pool_created_at")}}
    result = audit(mint, pool, chain, holders)
    cooldown = min(1440, RETRY_MINUTES * (2 ** min(attempts - 1, 4)))
    result["metrics"]["rpc_queue"] = {
        "attempts": attempts,
        "last_attempt_at": datetime.now(timezone.utc).isoformat(),
        "next_attempt_at": (datetime.now(timezone.utc) + timedelta(minutes=cooldown)).isoformat(),
        "max_attempts": MAX_ATTEMPTS,
        "last_rate_limited": throttled,
    }
    db("PATCH", "token_audits?mint=eq." + urllib.parse.quote(mint, safe=""),
       {k:v for k,v in result.items() if k != "mint"})
    print("RPC audit",mint[:8],"onchain",chain.get("status"),
          "concentration",holders.get("status"),
          "failed_method",holders.get("failed_method"),
          "error_kind",holders.get("error_kind"),"rate_limited",throttled)

def main():
    if not URL or not KEY:
        raise RuntimeError("Missing Supabase environment configuration")
    rows = candidates()
    for row in rows[:LIMIT]:
        process(row)
    print("RPC queue candidates",len(rows),"processed",min(len(rows),LIMIT))

if __name__ == "__main__":
    main()
