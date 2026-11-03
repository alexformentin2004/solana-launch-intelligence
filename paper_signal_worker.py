"""Persist explainable scanner decisions. No simulated fills or wallet operations."""
import json
import os
from datetime import datetime, timezone
from collector import request_json, db

URL = os.environ.get("SUPABASE_URL","").rstrip("/")
KEY = os.environ.get("SUPABASE_SERVICE_ROLE_KEY","")

def fetch(table, fields, extra):
    return request_json(URL+"/rest/v1/"+table+"?select="+fields+extra,
        {"apikey":KEY,"Authorization":"Bearer "+KEY}) or []

def decide(launch, snap, audit):
    age = (datetime.fromisoformat(snap["observed_at"].replace("Z","+00:00"))-
           datetime.fromisoformat(launch["created_at"].replace("Z","+00:00"))).total_seconds()
    liquidity=float(snap.get("liquidity_usd") or 0)
    volume=float(snap.get("volume_5m_usd") or 0)
    buys=int(snap.get("buys_5m") or 0)
    sells=int(snap.get("sells_5m") or 0)
    risk=(audit or {}).get("risk_level") or "unknown"
    reasons=[]
    if age>300: reasons.append("detected_after_300s")
    if age<0: reasons.append("invalid_age")
    if liquidity<10000: reasons.append("liquidity_below_10000")
    if volume<3000: reasons.append("volume_5m_below_3000")
    if buys<10: reasons.append("buys_5m_below_10")
    if sells>0 and buys/sells<1.5: reasons.append("buy_sell_ratio_below_1_5")
    # Market research eligibility is distinct from verified safety.
    # The current auditor never produces 'low'; 'medium' is NOT safe to trade.
    if risk in ("high", "unknown"): reasons.append("risk_high_or_unknown")
    if risk not in ("low", "medium"): reasons.append("risk_unverified")
    # Research gate only: candidate is NOT a recommendation or executable entry.
    decision="candidate" if not reasons else "watch" if reasons==["detected_after_300s"] else "reject"
    return {"mint":launch["mint"],"decision":decision,
        "reason":",".join(reasons) if reasons else "research_filters_passed",
        "age_seconds":int(age),"liquidity_usd":snap.get("liquidity_usd"),
        "volume_5m_usd":snap.get("volume_5m_usd"),"buys_5m":buys,"sells_5m":sells,
        "price_usd":snap.get("price_usd"),"risk_level":risk,
        "strategy_version":"market_research_v2_unverified_risk","simulated_order":False}

def main():
    if not URL or not KEY: raise RuntimeError("missing credentials")
    launches=fetch("launches","mint,created_at,first_seen_at","&order=first_seen_at.desc&limit=100")
    existing={x["mint"] for x in fetch("paper_signals","mint","&limit=1000")}
    pending=[x for x in launches if x["mint"] not in existing and x.get("created_at")]
    if not pending:
        print("PAPER_SIGNALS",json.dumps({"new":0,"orders":0}))
        return
    snapshots=fetch("token_snapshots","mint,observed_at,price_usd,liquidity_usd,volume_5m_usd,buys_5m,sells_5m","&order=observed_at.desc&limit=1000")
    audits=fetch("token_audits","mint,risk_level","&limit=1000")
    first={}
    for x in snapshots:
        first.setdefault(x["mint"],x)
    risk={x["mint"]:x for x in audits}
    rows=[]
    for launch in pending:
        snap=first.get(launch["mint"])
        if not snap: continue
        try: rows.append(decide(launch,snap,risk.get(launch["mint"])))
        except (ValueError,TypeError,KeyError): continue
    db("paper_signals",rows,"resolution=ignore-duplicates,return=minimal","mint")
    counts={k:sum(x["decision"]==k for x in rows) for k in ("candidate","watch","reject")}
    print("PAPER_SIGNALS",json.dumps({"new":len(rows),"classification":counts,"orders":0},sort_keys=True))

if __name__=="__main__": main()
