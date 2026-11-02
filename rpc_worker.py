"""Bounded RPC audit queue. Existing token_audits rows are the durable queue."""
import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from onchain import mint_checks
from concentration import concentration
from auditor import audit

URL = os.environ.get("SUPABASE_URL", "").rstrip("/")
KEY = os.environ.get("SUPABASE_SERVICE_ROLE_KEY", "")
LIMIT = 1
RETRY_MINUTES = 60

def db(method, path, data=None):
    headers = {"apikey": KEY, "Authorization": "Bearer " + KEY,
               "Content-Type": "application/json", "Accept": "application/json",
               "Prefer": "return=minimal"}
    payload = json.dumps(data).encode() if data is not None else None
    request = urllib.request.Request(URL + "/rest/v1/" + path, data=payload,
                                     headers=headers, method=method)
    with urllib.request.urlopen(request, timeout=20) as response:
        return json.load(response) if method == "GET" else None

def candidates():
    # Retry only older audits to avoid repeated 429 bursts; newly discovered audits wait for the cooldown.
    cutoff = (datetime.now(timezone.utc) - timedelta(minutes=RETRY_MINUTES)).isoformat()
    path = ("token_audits?select=mint,metrics,audited_at&"
            "order=audited_at.asc&limit=100&audited_at=lt." +
            urllib.parse.quote(cutoff, safe=""))
    rows = db("GET", path)
    return [r for r in rows if (r.get("metrics") or {}).get("onchain", {}).get("status") != "verified"
            or (r.get("metrics") or {}).get("concentration", {}).get("status") != "verified"]

def process(row):
    mint = row["mint"]
    old = row.get("metrics") or {}
    chain = old.get("onchain") or {"status":"not_checked"}
    holders = old.get("concentration") or {"status":"not_checked"}
    throttled = False
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
    db("PATCH", "token_audits?mint=eq." + urllib.parse.quote(mint, safe=""),
       {k:v for k,v in result.items() if k != "mint"})
    print("RPC audit",mint[:8],"onchain",chain.get("status"),
          "concentration",holders.get("status"),"rate_limited",throttled)

def main():
    if not URL or not KEY:
        raise RuntimeError("Missing Supabase environment configuration")
    rows = candidates()
    for row in rows[:LIMIT]:
        process(row)
    print("RPC queue candidates",len(rows),"processed",min(len(rows),LIMIT))

if __name__ == "__main__":
    main()
