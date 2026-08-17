import unittest

import app as app_module


class SectionNameTests(unittest.TestCase):
    def test_sanitize_string_preserves_apostrophes_for_storage(self):
        """Escaping text before storage would expose HTML entities in the UI."""
        self.assertEqual(app_module.sanitize_string("  Artist's <ideas>  "), "Artist's <ideas>")

if __name__ == "__main__":
    unittest.main()
