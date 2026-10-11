import unittest

from main import alert_sort_key, classify_priority, format_alert


class AlertPriorityTests(unittest.TestCase):
    def test_priority_order(self):
        self.assertEqual(classify_priority("National Emergency Message"), "Emergency")
        self.assertEqual(classify_priority("Tornado Warning"), "Warning")
        self.assertEqual(classify_priority("Severe Thunderstorm Watch"), "Watch")
        self.assertEqual(classify_priority("Winter Weather Advisory"), "Advisory")
        self.assertEqual(classify_priority("Special Weather Statement"), "Statement")

    def test_sort_orders_emergency_before_warning(self):
        emergency = {"properties": {"event": "Evacuation Immediate", "effective": "2026-10-11T12:00:00Z"}}
        warning = {"properties": {"event": "Tornado Warning", "effective": "2026-10-11T11:00:00Z"}}
        self.assertLess(alert_sort_key(emergency), alert_sort_key(warning))

    def test_format_alert_preserves_source_fields(self):
        feature = {"properties": {
            "event": "Tornado Warning",
            "headline": "Tornado Warning for Test County",
            "areaDesc": "Test County",
            "description": "Take shelter now.",
            "instruction": "Move to an interior room.",
        }}
        result = format_alert(feature)
        self.assertIn("Tornado Warning", result)
        self.assertIn("Test County", result)
        self.assertIn("Take shelter now.", result)
        self.assertIn("Move to an interior room.", result)


if __name__ == "__main__":
    unittest.main()
