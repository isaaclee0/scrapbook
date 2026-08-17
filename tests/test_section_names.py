import unittest
from unittest.mock import patch

import app as app_module


USER = {"id": 7, "email": "owner@example.test"}


class FakeCursor:
    def __init__(self, results):
        self.results = iter(results)
        self.current = None

    def execute(self, _query, _params=()):
        self.current = next(self.results)

    def fetchone(self):
        return self.current

    def fetchall(self):
        return self.current or []

    def close(self):
        pass


class FakeConnection:
    def __init__(self, results):
        self.cursor_instance = FakeCursor(results)

    def cursor(self, **_kwargs):
        return self.cursor_instance

    def close(self):
        pass


class SectionNameTests(unittest.TestCase):
    def test_sanitize_string_preserves_apostrophes_for_storage(self):
        """Escaping text before storage would expose HTML entities in the UI."""
        self.assertEqual(app_module.sanitize_string("  Artist's <ideas>  "), "Artist's <ideas>")

    def test_board_decodes_legacy_section_entities_before_rendering(self):
        """Leaving already-stored entities encoded would keep showing &#x27; to users."""
        connection = FakeConnection([
            {"id": 9, "user_id": 7, "name": "Inspiration"},
            [{
                "id": 3,
                "board_id": 9,
                "name": "Artist&#x27;s ideas",
                "pin_count": 0,
                "default_image_url": None,
            }],
            {"total": 0},
            None,
            [],
            [],
        ])
        app_module.app.config.update(TESTING=True)

        with patch.object(app_module, "get_current_user", return_value=USER), \
             patch.object(app_module, "get_db_connection", return_value=connection), \
             patch.object(app_module, "render_template", return_value="rendered") as render:
            response = app_module.app.test_client().get("/board/9")

        self.assertEqual(response.status_code, 200)
        sections = render.call_args.kwargs["sections"]
        self.assertEqual(sections[0]["name"], "Artist's ideas")


if __name__ == "__main__":
    unittest.main()
