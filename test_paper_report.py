import unittest
from datetime import datetime, timedelta, timezone
from paper_report import evaluate

class ReportTests(unittest.TestCase):
    def test_missing_entry_window(self):
        start = datetime(2026, 1, 1, tzinfo=timezone.utc)
        samples = [{"observed_at": (start + timedelta(minutes=5)).isoformat(), "price_usd": "1"}]
        self.assertEqual(evaluate({"created_at": start.isoformat()}, samples)["reason"],
                         "no_entry_sample_30_to_90_seconds")

    def test_eligible_replay(self):
        start = datetime(2026, 1, 1, tzinfo=timezone.utc)
        samples = [{"observed_at": (start + timedelta(seconds=s)).isoformat(), "price_usd": p}
                   for s, p in [(45, "1"), (55, "2"), (65, "3"), (75, "4")]]
        self.assertEqual(evaluate({"created_at": start.isoformat()}, samples)["status"], "approximate")

    def test_missing_creation_time(self):
        self.assertEqual(evaluate({}, [])["reason"], "unknown_pool_creation_time")

if __name__ == "__main__":
    unittest.main()
