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

def simulate(launch, bars):
    bars = sorted(bars, key=lambda x:x["candle_at"])
    born = ts(launch["created_at"])
    candidates = [i for i,b in enumerate(bars) if 30 <= ts(b["candle_at"])-born <= 90]
    if not candidates:
        return {"status":"no_entry"}
    idx = candidates[0]
    if idx+1 >= len(bars):
        return {"status":"no_followup"}
    entry = float(bars[idx]["open_usd"])
    if entry <= 0:
        return {"status":"invalid"}
    remaining, proceeds, stop, next_tp = 1.0, 0.0, .82, 0
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

if __name__=="__main__":
    main()
