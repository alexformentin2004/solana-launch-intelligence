"""Solana new-pool observer; standard-library-only cloud worker."""
import json
import time
import os
import sys
import urllib.error
import urllib.request
from auditor import audit
from onchain import mint_checks
from concentration import concentration as account_concentration
from datetime import datetime, timezone

API = "https://api.geckoterminal.com/api/v2/networks/solana/new_pools?page=1"
URL = os.environ.get("SUPABASE_URL", "").rstrip("/")
KEY = os.environ.get("SUPABASE_SERVICE_ROLE_KEY", "")

def request_json(url, headers=None, method="GET", data=None):
    payload = None if data is None else json.dumps(data).encode()
    req = urllib.request.Request(url, data=payload, method=method, headers={
        "Accept": "application/json", "User-Agent": "solana-launch-intelligence/0.1",
        **(headers or {}),
    })
    try:
        with urllib.request.urlopen(req, timeout=25) as response:
            body = response.read()
            return json.loads(body) if body else None
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:700]
        raise ValueError(f"HTTP {exc.code} from {url.split('?')[0]}: {detail}") from exc

def db(table, records, prefer="resolution=merge-duplicates,return=minimal", on_conflict=None):
    if not records:
        return
    url = f"{URL}/rest/v1/{table}"
    if on_conflict:
        url += f"?on_conflict={on_conflict}"
    request_json(url, {
        "apikey": KEY,
        "Authorization": f"Bearer {KEY}",
        "Content-Type": "application/json",
        "Prefer": prefer,
    }, "POST", records)

def main():
    if not URL or not KEY:
        print("Missing SUPABASE_URL or SUPABASE_SERVICE_ROLE_KEY", file=sys.stderr)
        return 2
    now = datetime.now(timezone.utc).isoformat()
    run = {"source": "geckoterminal_new_pools", "started_at": now, "status": "running"}
    try:
        response = request_json(API)
        pools = response.get("data", [])
        launches, snapshots, audits = {}, {}, {}
        rpc_attempts = 0
        rpc_limited = False
        for pool in pools:
            attrs = pool.get("attributes") or {}
            rel = (pool.get("relationships") or {}).get("base_token") or {}
            token_id = ((rel.get("data") or {}).get("id") or "")
            mint = token_id.removeprefix("solana_")
            if not mint or mint == token_id:
                continue
            created = attrs.get("pool_created_at")
            launches[mint] = {
                "mint": mint, "source": "geckoterminal_new_pools",
                "created_at": created, "first_seen_at": now, "last_seen_at": now,
                "raw": {"pool_id": pool.get("id"), "pool_name": attrs.get("name")},
            }
            chain = None
            if mint not in audits and rpc_attempts < 3 and not rpc_limited:
                rpc_attempts += 1
                try:
                    chain = mint_checks(mint)
                except (OSError, ValueError, KeyError, TypeError) as exc:
                    if getattr(exc, "code", None) == 429:
                        rpc_limited = True
                    chain = {"status":"error","error_type":type(exc).__name__,
                             "error_detail":str(exc)[:180]}
                    print(f"Optional RPC check unavailable for {mint[:8]}: {type(exc).__name__}: {str(exc)[:180]}")
            concentration = None
            if chain is not None and chain.get("status") == "verified" and not rpc_limited:
                time.sleep(1.2)
                try:
                    concentration = account_concentration(mint)
                except (OSError, ValueError, KeyError, TypeError) as exc:
                    if getattr(exc, "code", None) == 429:
                        rpc_limited = True
                    concentration = {"status":"error","error_type":type(exc).__name__,
                                     "error_detail":str(exc)[:180]}
                    print(f"Optional concentration check unavailable for {mint[:8]}: {type(exc).__name__}: {str(exc)[:180]}")
            audits[mint] = audit(mint, pool, chain, concentration)
            if chain is not None and not rpc_limited:
                time.sleep(1.2)
            snapshots[mint] = {
                "mint": mint, "observed_at": now,
                "price_usd": attrs.get("base_token_price_usd"),
                "liquidity_usd": attrs.get("reserve_in_usd"),
                "volume_5m_usd": (attrs.get("volume_usd") or {}).get("m5"),
                "buys_5m": (attrs.get("transactions") or {}).get("m5", {}).get("buys"),
                "sells_5m": (attrs.get("transactions") or {}).get("m5", {}).get("sells"),
                "raw": {"pool_id": pool.get("id")},
            }
        # Preserve original first_seen_at and created_at for previously discovered tokens.
        # Ignore conflicts rather than overwriting historical launch metadata.
        db("launches", list(launches.values()), "resolution=ignore-duplicates,return=minimal", "mint")
        db("token_snapshots", list(snapshots.values()))
        db("token_audits", list(audits.values()), on_conflict="mint")
        db("collection_runs", [{**run, "finished_at": datetime.now(timezone.utc).isoformat(),
                                "status": "success", "items_seen": len(pools),
                                "items_written": len(snapshots)}], "return=minimal")
        print(f"Pools={len(pools)} tokens={len(launches)} snapshots={len(snapshots)} audits={len(audits)}")
        return 0
    except (urllib.error.URLError, ValueError, KeyError, TypeError) as exc:
        print(f"Collection failed: {exc}", file=sys.stderr)
        try:
            db("collection_runs", [{**run, "finished_at": datetime.now(timezone.utc).isoformat(),
                                    "status": "error", "error_message": str(exc)[:1000]}], "return=minimal")
        except Exception:
            pass
        return 1

if __name__ == "__main__":
    sys.exit(main())
