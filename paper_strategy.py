"""Conservative, offline paper-trading replay of observed token snapshots.

Not a live trading engine. Sparse observations cannot establish whether an
intrabar stop or take-profit executed; this replay is explicitly approximate.
"""
from datetime import datetime

INITIAL_STOP = -18.0
TARGETS = ((100.0, 0.40, 85.0), (200.0, 0.40, 150.0), (300.0, 0.20, None))

def replay(samples, entry_index=0, max_gap_seconds=90):
    """Replay a single hypothetical position, with TP sizes of ORIGINAL quantity.

    Requires positive numeric prices, chronological timestamps and adequate
    sampling. Stops are modeled at the observed price (never guaranteed).
    No interpolation or invented fills. Return insufficient_data on gaps.
    """
    points = []
    for item in samples:
        try:
            price = float(item["price_usd"])
            stamp = datetime.fromisoformat(str(item["observed_at"]).replace("Z", "+00:00"))
        except (KeyError, TypeError, ValueError, OverflowError):
            continue
        if price > 0:
            points.append((stamp, price))
    points.sort(key=lambda x: x[0])
    if len(points) < 2 or entry_index >= len(points) - 1:
        return {"status": "insufficient_data", "reason": "need_multiple_prices"}
    for previous, current in zip(points, points[1:]):
        if (current[0] - previous[0]).total_seconds() > max_gap_seconds:
            return {"status": "insufficient_data", "reason": "sampling_gap",
                    "gap_seconds": (current[0] - previous[0]).total_seconds()}
    entry = points[entry_index][1]
    remaining = 1.0
    proceeds = 0.0
    stop = INITIAL_STOP
    target_index = 0
    events = []
    for stamp, price in points[entry_index + 1:]:
        change = (price / entry - 1) * 100
        if change <= stop:
            proceeds += remaining * price / entry
            events.append({"type": "stop", "observed_at": stamp.isoformat(),
                           "change_pct": round(change, 3), "sold_fraction": round(remaining, 6)})
            remaining = 0
            break
        while target_index < len(TARGETS) and change >= TARGETS[target_index][0]:
            threshold, fraction, new_stop = TARGETS[target_index]
            # Fill at observed price, not at an invented threshold quote.
            proceeds += fraction * price / entry
            remaining = max(0, remaining - fraction)
            events.append({"type": "take_profit", "target_pct": threshold,
                           "observed_at": stamp.isoformat(), "change_pct": round(change, 3),
                           "sold_fraction": fraction})
            target_index += 1
            if new_stop is not None:
                stop = max(stop, new_stop)
        if remaining < 1e-8:
            remaining = 0
            break
    if remaining:
        # Mark-to-market is not realized profit.
        mark = remaining * points[-1][1] / entry
    else:
        mark = 0.0
    return {"status": "approximate", "entry_price": entry, "remaining_fraction": round(remaining, 6),
            "realized_return_pct": round((proceeds - (1 - remaining)) * 100, 3),
            "total_marked_return_pct": round((proceeds + mark - 1) * 100, 3),
            "events": events, "sampling_warning": "snapshot prices are not executable quotes",
            "costs_included": False}
