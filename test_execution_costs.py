import unittest
from execution_costs import ExecutionCosts, apply_costs
from paper_strategy import replay

def points(prices):
    return [{"observed_at": "2026-01-01T00:00:%02d+00:00" % (i*10),
             "price_usd": p} for i,p in enumerate(prices)]

class ExecutionCostsTests(unittest.TestCase):
    def test_zero_costs_preserve_marked_result(self):
        result = replay(points([1,2,3,4]))
        adjusted = apply_costs(result, ExecutionCosts(0,0,0,0,0))
        self.assertAlmostEqual(adjusted["estimated_net_marked_return_pct"],
                               result["total_marked_return_pct"])

    def test_costs_reduce_profit(self):
        result = replay(points([1,2,3,4]))
        adjusted = apply_costs(result)
        self.assertLess(adjusted["estimated_net_marked_return_pct"],
                        result["total_marked_return_pct"])

    def test_open_position_has_liquidation_cost(self):
        result = replay(points([1,1.2]))
        adjusted = apply_costs(result)
        self.assertEqual(result["remaining_fraction"], 1)
        self.assertLess(adjusted["estimated_net_marked_return_pct"], 20)

    def test_insufficient_data_not_costed(self):
        self.assertFalse(apply_costs({"status": "insufficient_data"})["costs_applied"])

    def test_invalid_costs(self):
        with self.assertRaises(ValueError):
            ExecutionCosts(entry_fee_pct=-1)

if __name__ == "__main__":
    unittest.main()
