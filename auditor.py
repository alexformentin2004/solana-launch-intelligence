"""Conservative research-only audit. No trading, no private keys, no paid API."""
from datetime import datetime, timezone

def audit(mint, pool):
    attrs = pool.get("attributes") or {}
    liquidity = _number(attrs.get("reserve_in_usd"))
    vol = _number((attrs.get("volume_usd") or {}).get("m5"))
    tx = (attrs.get("transactions") or {}).get("m5") or {}
    buys, sells = int(tx.get("buys") or 0), int(tx.get("sells") or 0)
    created = attrs.get("pool_created_at")
    findings = []
    pending = ["mint_authority", "freeze_authority", "holder_concentration", "creator_wallet", "token_program", "liquidity_lock"]
    score = 50
    if liquidity is None:
        findings.append({"code":"liquidity_unknown","severity":"unknown"})
    elif liquidity < 1000:
        score += 30
        findings.append({"code":"very_low_liquidity","severity":"high"})
    elif liquidity < 10000:
        score += 15
        findings.append({"code":"low_liquidity","severity":"medium"})
    elif liquidity >= 50000:
        score -= 10
        findings.append({"code":"higher_liquidity","severity":"info"})
    if buys + sells >= 10 and sells > buys * 3:
        score += 15
        findings.append({"code":"sell_pressure","severity":"medium"})
    if vol is not None and liquidity and vol > liquidity * 5:
        score += 10
        findings.append({"code":"high_volume_to_liquidity","severity":"medium"})
    score = max(0,min(100,score))
    # Unknown critical checks prohibit a low-risk verdict.
    level = "high" if score >= 70 else "medium" if score >= 40 else "unknown"
    return {"mint":mint,"audited_at":datetime.now(timezone.utc).isoformat(),
            "risk_score":score,"risk_level":level,"confidence":"limited",
            "findings":findings,"checks_pending":pending,
            "metrics":{"liquidity_usd":liquidity,"volume_5m_usd":vol,"buys_5m":buys,
                       "sells_5m":sells,"pool_created_at":created}}

def _number(v):
    try:
        return float(v) if v is not None else None
    except (TypeError,ValueError):
        return None
