"""Transparent fee/slippage assumptions for *hypothetical* paper trades.

Amounts are normalized to one unit of initial notional. This is NOT a DEX
quote or a guarantee of execution. All parameters are explicit and configurable.
"""
from dataclasses import dataclass

@dataclass(frozen=True)
class ExecutionCosts:
    entry_fee_pct: float = 0.5
    exit_fee_pct: float = 0.5
    entry_slippage_pct: float = 1.0
    exit_slippage_pct: float = 1.0
    fixed_cost_pct_of_initial: float = 0.0

    def __post_init__(self):
        for name, value in vars(self).items():
            if not 0 <= value < 100:
                raise ValueError(name + " must be in [0,100)")

def apply_costs(replay_result, costs=None):
    """Adjust a completed or open replay using explicit simplified costs.

    Entry fee applies to initial notional; exits to sold notional.
    Open holdings are marked at a hypothetical liquidation value and exit
    costs on that mark are included in estimated net marked return.
    """
    costs = costs or ExecutionCosts()
    if replay_result.get("status") != "approximate":
        return {**replay_result, "costs_applied": False}
    entry = replay_result["entry_price"]
    remaining = replay_result["remaining_fraction"]
    if entry <= 0 or not 0 <= remaining <= 1:
        raise ValueError("invalid replay")
    exit_factor = (1 - costs.exit_slippage_pct / 100) * (1 - costs.exit_fee_pct / 100)
    entry_factor = (1 + costs.entry_slippage_pct / 100) * (1 + costs.entry_fee_pct / 100)
    # Every sale's gross value is recorded at the sampled price, relative to
    # original entry price. Marked holdings are treated as a hypothetical exit.
    sold_gross = sum(event["sold_fraction"] * (1 + event["change_pct"] / 100)
                     for event in replay_result["events"])
    gross_total = 1 + replay_result["total_marked_return_pct"] / 100
    marked_gross = max(0, gross_total - sold_gross)
    net_realized_cash = sold_gross * exit_factor
    net_marked_cash = marked_gross * exit_factor
    net_total_pct = (net_realized_cash + net_marked_cash - entry_factor
                     - costs.fixed_cost_pct_of_initial / 100) * 100
    return {**replay_result,
            "estimated_net_marked_return_pct": round(net_total_pct, 3),
            "estimated_net_realized_pnl_pct_initial": round(
                (net_realized_cash - entry_factor * (1 - remaining)
                 - costs.fixed_cost_pct_of_initial / 100) * 100, 3),
            "costs_applied": True,
            "cost_assumptions": vars(costs).copy(),
            "execution_warning": "Modeled costs only; no spread, impact, gas variability, MEV, failed fills or latency."}
