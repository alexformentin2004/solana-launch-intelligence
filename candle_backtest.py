"""Exploratory OHLC backtest of saved candles, NOT executable trades.

Entry uses the OPEN of the first candle beginning 30-90s after pool creation.
This is a proxy, not proof of a fill at that time. Stop wins intrabar ties.
Any missing minute before closure censors the trade; never score it as a win.
"""
import json
import os
from datetime import datetime
from collector import request_json
from execution_costs import ExecutionCosts

def ts(s):
    return datetime.fromisoformat(str(s).replace("Z","+00:00")).timestamp()

def simulate(launch, bars, entry_delay=30, initial_stop=.82, targets=None):
    bars = sorted(bars, key=lambda x:x["candle_at"])
    born = ts(launch["created_at"])
    candidates = [i for i,b in enumerate(bars) if entry_delay <= ts(b["candle_at"])-born <= entry_delay+60]
    if not candidates:
        return {"status":"no_entry"}
    idx = candidates[0]
    if idx+1 >= len(bars):
        return {"status":"no_followup"}
    entry = float(bars[idx]["open_usd"])
    if entry <= 0:
        return {"status":"invalid"}
    remaining, proceeds, stop, next_tp = 1.0, 0.0, initial_stop, 0
    if targets is None:
        targets = [(2.,.4,1.85),(3.,.4,2.5),(4.,.2,None)]
    events=[]
    prev=ts(bars[idx]["candle_at"])
    for b in bars[idx+1:]:
        now=ts(b["candle_at"])
        if now-prev != 60:
            return {"status":"censored_gap","events":events}
        prev=now
        op,hi,lo,cl=[float(b[k]) / entry for k in ("open_usd","high_usd","low_usd","close_usd")]
        if min(op,hi,lo,cl)<=0:
            return {"status":"invalid"}
        # Conservative intrabar ordering: stop before any TP, including gaps.
        if op<=stop or lo<=stop:
            fill=min(op,stop)
            proceeds+=remaining*fill
            events.append("stop")
            remaining=0.
            break
        while next_tp<len(targets) and hi>=targets[next_tp][0]:
            target,frac,new_stop=targets[next_tp]
            proceeds+=frac*target
            remaining=max(0.,remaining-frac)
            events.append("tp"+str(next_tp+1))
            next_tp+=1
            if new_stop is not None:
                stop=max(stop,new_stop)
        if remaining<1e-9:
            break
    if remaining:
        # No final liquidation evidence: marked at last close only.
        proceeds+=remaining*float(bars[-1]["close_usd"])/entry
    costs=ExecutionCosts()
    entry_cost=(1+costs.entry_fee_pct/100)*(1+costs.entry_slippage_pct/100)
    exit_factor=(1-costs.exit_fee_pct/100)*(1-costs.exit_slippage_pct/100)
    return {"status":"closed" if not remaining else "open_marked",
            "gross_pct":round((proceeds-1)*100,3),
            "net_pct":round((proceeds*exit_factor-entry_cost)*100,3),
            "events":events}

def fetch_all(url, headers, page_size=500):
    """Read every PostgREST page; never silently backtest a truncated sample."""
    rows = []
    offset = 0
    while True:
        separator = "&" if "?" in url else "?"
        page = request_json(f"{url}{separator}limit={page_size}&offset={offset}", headers) or []
        if not isinstance(page, list):
            raise ValueError("Expected a list from Supabase")
        rows.extend(page)
        if len(page) < page_size:
            return rows
        offset += len(page)

def main():
    url=os.environ["SUPABASE_URL"].rstrip("/")
    key=os.environ["SUPABASE_SERVICE_ROLE_KEY"]
    headers={"apikey":key,"Authorization":"Bearer "+key}
    cohort=fetch_all(url+"/rest/v1/historical_cohort?select=mint,created_at&order=first_seen_at.asc,mint.asc",headers)
    candles=fetch_all(url+"/rest/v1/historical_candles?select=mint,candle_at,open_usd,high_usd,low_usd,close_usd&order=mint.asc,candle_at.asc",headers)
    print("BACKTEST_INPUT",json.dumps({"cohort":len(cohort),"candles":len(candles)}))
    by_mint={}
    for b in candles:
        by_mint.setdefault(b["mint"],[]).append(b)
    classifications={}
    trades=[]
    for launch in cohort:
        if launch["mint"] not in by_mint:
            continue
        result=simulate(launch,by_mint[launch["mint"]])
        status=result["status"]
        classifications[status]=classifications.get(status,0)+1
        if status in ("closed","open_marked"):
            trades.append(result)
    closed=[r for r in trades if r["status"]=="closed"]
    def stats(items):
        if not items:return None
        return {"n":len(items),"mean_net_pct":round(sum(r["net_pct"] for r in items)/len(items),3),
                "positive_net":sum(r["net_pct"]>0 for r in items),
                "mean_gross_pct":round(sum(r["gross_pct"] for r in items)/len(items),3)}
    print("CANDLE_BACKTEST",json.dumps({
        "frozen_cohort":len(cohort),"tokens_with_candles":len(by_mint),
        "classification":classifications,"closed_only":stats(closed),
        "closed_and_open_marked":stats(trades),
        "costs":"0.5% entry/exit fees, 1% entry/exit slippage",
        "warning":"Exploratory, sparse OHLC; entry open proxy; intrabar stop first; no actual execution; no valid strategy ROI."
    },sort_keys=True))

    def compare(label, delay=30, stop=.82, targets=None):
        groups = {}
        for launch in cohort:
            bars = by_mint.get(launch["mint"], [])
            if not bars:
                continue
            outcome = simulate(launch, bars, entry_delay=delay, initial_stop=stop, targets=targets)
            groups.setdefault(outcome["status"], []).append(outcome)
        completed = groups.get("closed", [])
        marked = completed + groups.get("open_marked", [])
        def summary(items):
            return {"n": len(items), "positive": sum(v["net_pct"] > 0 for v in items),
                    "mean_net_pct": round(sum(v["net_pct"] for v in items) / len(items), 3) if items else None}
        print("SENSITIVITY", json.dumps({"label":label,"entry_delay_seconds":delay,
            "classification":{k:len(v) for k,v in groups.items()},
            "closed":summary(completed),"closed_plus_marked":summary(marked),
            "tp1":sum("tp1" in v.get("events",[]) for v in marked),
            "tp2":sum("tp2" in v.get("events",[]) for v in marked),
            "tp3":sum("tp3" in v.get("events",[]) for v in marked)},sort_keys=True))
    for delay in (30,60,90):
        compare("entry_timing",delay)
    for label,stop,targets in (
        ("stop_12",.88,None),
        ("stop_25",.75,None),
        ("tp_50_100",.82,[(1.5,.5,1.),(2.,.5,None)]),
        ("tp_100_200",.82,[(2.,.5,1.85),(3.,.5,None)]),
    ):
        compare(label,30,stop,targets)
    quality = {"one_bar":0,"two_to_five":0,"six_to_ten":0,"over_ten":0,"any_gap":0}
    for bars in by_mint.values():
        n = len(bars)
        quality["one_bar" if n==1 else "two_to_five" if n<=5 else "six_to_ten" if n<=10 else "over_ten"] += 1
        if any(ts(bars[i]["candle_at"])-ts(bars[i-1]["candle_at"]) != 60 for i in range(1,n)):
            quality["any_gap"] += 1
    print("CANDLE_QUALITY",json.dumps(quality,sort_keys=True))

if __name__=="__main__":
    main()
