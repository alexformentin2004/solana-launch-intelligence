import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch
from persistent_monitor import candidate, discover

class PersistentMonitorTests(unittest.TestCase):
    def test_candidate_recent(self):
        now = datetime(2026, 11, 2, tzinfo=timezone.utc)
        pool = {"id": "solana_" + "A"*40,
                "attributes": {"pool_created_at": (now - timedelta(seconds=40)).isoformat()},
                "relationships": {"base_token": {"data": {"id": "solana_" + "B"*40}}}}
        self.assertEqual(candidate(pool, now)[0], "B"*40)

    def test_candidate_old(self):
        now = datetime(2026, 11, 2, tzinfo=timezone.utc)
        pool = {"id": "solana_" + "A"*40,
                "attributes": {"pool_created_at": (now - timedelta(hours=1)).isoformat()},
                "relationships": {"base_token": {"data": {"id": "solana_" + "B"*40}}}}
        self.assertIsNone(candidate(pool, now))

    def test_discover_bounded(self):
        now = datetime(2026, 11, 2, tzinfo=timezone.utc)
        pool = {"id": "solana_" + "A"*40,
                "attributes": {"pool_created_at": now.isoformat()},
                "relationships": {"base_token": {"data": {"id": "solana_" + "B"*40}}}}
        with patch("persistent_monitor.request_json", return_value={"data": [pool]}), patch("persistent_monitor.db") as write:
            active = {}
            self.assertEqual(discover(now, active), 1)
            self.assertEqual(discover(now, active), 0)
            self.assertEqual(write.call_count, 1)

if __name__ == "__main__":
    unittest.main()
