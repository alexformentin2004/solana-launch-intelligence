import unittest
from datetime import datetime, timedelta, timezone
from paper_strategy import replay

def series(prices, spacing=10):
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    return [{"observed_at": (start + timedelta(seconds=i * spacing)).isoformat(),
             "price_usd": price} for i, price in enumerate(prices)]

class PaperStrategyTests(unittest.TestCase):
    def test_all_targets(self):
        result = replay(series([1, 2, 3, 4]))
        self.assertEqual(result["status"], "approximate")
        self.assertEqual(result["remaining_fraction"], 0)
        self.assertEqual(len(result["events"]), 3)
        self.assertAlmostEqual(result["total_marked_return_pct"], 180)

    def test_stop_before_target(self):
        result = replay(series([1, 0.8]))
        self.assertEqual(result["events"][0]["type"], "stop")
        self.assertAlmostEqual(result["total_marked_return_pct"], -20)

    def test_stop_after_first_target(self):
        result = replay(series([1, 2, 1.8]))
        self.assertEqual(result["events"][-1]["type"], "stop")
        self.assertAlmostEqual(result["total_marked_return_pct"], 88)

    def test_sparse_data_rejected(self):
        self.assertEqual(replay(series([1, 2], 300))["status"], "insufficient_data")

    def test_unfinished_position_is_marked(self):
        result = replay(series([1, 1.2]))
        self.assertEqual(result["remaining_fraction"], 1)
        self.assertAlmostEqual(result["total_marked_return_pct"], 20)
        self.assertAlmostEqual(result["realized_return_pct"], 0)

if __name__ == "__main__":
    unittest.main()
