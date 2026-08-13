import unittest
from unittest.mock import patch

import app as app_module


USER = {"id": 7, "email": "owner@example.test"}
PIN = {
    "id": 42,
    "user_id": 7,
    "board_id": 9,
    "section_id": 3,
    "section_name": "Ideas",
    "board_name": "Inspiration",
    "title": "A complete pin",
    "description": "Description",
    "notes": "Notes",
    "image_url": "https://images.example.test/pin.jpg",
    "link": "https://source.example.test/article",
    "link_status": "live",
    "archive_url": None,
    "cached_filename": None,
    "cached_width": 640,
    "cached_height": 480,
    "dominant_color_1": "#112233",
    "dominant_color_2": "#445566",
}
CARD_PIN = {
    key: PIN[key] for key in (
        "id", "board_id", "section_id", "section_name", "board_name", "title",
        "image_url", "link", "link_status", "cached_filename", "cached_width",
        "cached_height", "dominant_color_1", "dominant_color_2",
    )
}


class FakeCursor:
    def __init__(self, results):
        self.results = iter(results)
        self.executions = []

    def execute(self, query, params=()):
        self.last_query = query
        self.last_params = params
        self.executions.append((query, params))
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

    def commit(self):
        pass

    def rollback(self):
        pass


class PinOverlayRouteTests(unittest.TestCase):
    def setUp(self):
        app_module.app.config.update(TESTING=True)
        self.client = app_module.app.test_client()
        self.current_user = patch.object(app_module, "get_current_user", return_value=USER)
        self.current_user.start()
        self.addCleanup(self.current_user.stop)

    def test_embedded_pin_accepts_matching_board(self):
        """Rejecting the supplied pin board would break a valid iframe."""
        connection = FakeConnection([PIN, [], []])
        with patch.object(app_module, "get_db_connection", return_value=connection):
            response = self.client.get("/pin/42?embedded=1&board_id=9")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(connection.cursor_instance.executions[2][1], (9, 7))

    def test_embedded_pin_rejects_different_board(self):
        """Removing board validation would expose a pin in the wrong iframe."""
        with patch.object(app_module, "get_db_connection", return_value=FakeConnection([PIN])):
            response = self.client.get("/pin/42?embedded=1&board_id=10")
        self.assertEqual(response.status_code, 404)

    def test_embedded_pin_requires_board_id(self):
        """Accepting an unbound iframe request would bypass board validation."""
        with patch.object(app_module, "get_db_connection", return_value=FakeConnection([PIN])):
            response = self.client.get("/pin/42?embedded=1")
        self.assertEqual(response.status_code, 404)

    def test_standalone_pin_does_not_require_board_id(self):
        """Applying iframe validation to standalone pins would break direct links."""
        with patch.object(app_module, "get_db_connection", return_value=FakeConnection([PIN, [], []])):
            response = self.client.get("/pin/42")
        self.assertEqual(response.status_code, 200)

    def test_standalone_pin_keeps_application_chrome(self):
        """Rendering direct links as embedded would hide normal application navigation."""
        with patch.object(app_module, "get_db_connection", return_value=FakeConnection([PIN, [], []])):
            response = self.client.get("/pin/42")
        html = response.get_data(as_text=True)
        self.assertIn('id="mainNav"', html)
        self.assertNotIn('data-embedded-pin="true"', html)

    def test_embedded_pin_marks_the_iframe_page_and_bridge(self):
        """Omitting embed markers or close bridge would leave an overlay without its controls."""
        with patch.object(app_module, "get_db_connection", return_value=FakeConnection([PIN, [], []])):
            response = self.client.get("/pin/42?embedded=1&board_id=9")
        html = response.get_data(as_text=True)
        self.assertIn('data-embedded-pin="true"', html)
        self.assertIn('embedded-pin-page', html)
        self.assertIn('scrappl-pin-overlay', html)
        self.assertIn('closePinView()', html)

    def test_embedded_section_moves_close_through_the_bridge(self):
        """Reloading an embedded section move would leave the parent overlay open."""
        with patch.object(app_module, "get_db_connection", return_value=FakeConnection([PIN, [], []])):
            response = self.client.get("/pin/42?embedded=1&board_id=9")
        html = response.get_data(as_text=True)
        section_move = html[html.index('function moveToSection'):html.index('function savePin')]
        self.assertIn("notifyPinOverlay('changed', 'updated');", section_move)
        self.assertIn('if (PIN_OVERLAY_EMBEDDED) closePinView();', section_move)
        self.assertIn('else window.location.reload();', section_move)

    def test_embedded_mutation_successes_use_the_namespaced_close_abstraction(self):
        """Reloading after an embedded mutation would discard the parent board state."""
        with patch.object(app_module, "get_db_connection", return_value=FakeConnection([PIN, [], []])):
            response = self.client.get("/pin/42?embedded=1&board_id=9")
        html = response.get_data(as_text=True)

        self.assertIn("source: 'scrappl-pin-overlay', version: 1", html)
        close_bridge = html[html.index('function closePinView'):html.index("document.addEventListener('DOMContentLoaded'")]
        self.assertIn("notifyPinOverlay('close')", close_bridge)
        self.assertIn('else window.history.back();', close_bridge)

        expectations = {
            'function moveToBoard': ("notifyPinOverlay('changed', 'moved');", 'function moveToSection'),
            'function moveToSection': ("notifyPinOverlay('changed', 'updated');", 'function savePin'),
            'function savePin()': ("notifyPinOverlay('changed', 'updated');", 'function confirmDelete'),
            'function deletePin': ("notifyPinOverlay('changed', 'deleted');", 'function setAsBoardImage'),
            'function savePinRenamedSection': ("notifyPinOverlay('changed', 'updated');", 'function createNewBoard'),
            'function saveTitle': ("notifyPinOverlay('changed', 'updated');", 'function enableUrlEdit'),
            'function saveUrl': ("notifyPinOverlay('changed', 'updated');", 'function toggleToolsMenu'),
            'function saveImage': ("notifyPinOverlay('changed', 'updated');", 'function checkUrlNow'),
            'function checkUrlNow': ("notifyPinOverlay('changed', 'updated');", 'function checkForArchive'),
        }
        for start, (notification, end) in expectations.items():
            with self.subTest(mutation=start):
                mutation = html[html.index(start):html.index(end, html.index(start))]
                self.assertEqual(mutation.count(notification), 1)
                if 'window.location.reload()' in mutation or 'window.location.href' in mutation:
                    self.assertIn('if (PIN_OVERLAY_EMBEDDED) closePinView();', mutation)
                    self.assertLess(mutation.index(notification), mutation.index('closePinView()'))

        archive = html[html.index('function checkForArchive'):html.index('</script>', html.index('function checkForArchive'))]
        archived_success = archive[archive.index('if (data.archived)'):archive.index('} else {', archive.index('if (data.archived)'))]
        self.assertEqual(archived_success.count("notifyPinOverlay('changed', 'updated');"), 1)

    def test_pin_card_returns_user_scoped_pin_contract(self):
        """Dropping card fields or user scope would break the overlay client."""
        connection = FakeConnection([CARD_PIN])
        with patch.object(app_module, "get_db_connection", return_value=connection):
            response = self.client.get("/api/pin/42/card")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json(), {"success": True, "pin": {
            "id": 42,
            "board_id": 9,
            "section_id": 3,
            "section_name": "Ideas",
            "board_name": "Inspiration",
            "title": "A complete pin",
            "image_url": "https://images.example.test/pin.jpg",
            "link": "https://source.example.test/article",
            "link_status": "live",
            "cached_filename": None,
            "cached_width": 640,
            "cached_height": 480,
            "dominant_color_1": "#112233",
            "dominant_color_2": "#445566",
        }})
        self.assertEqual(connection.cursor_instance.executions[0][1], (42, 7))
        self.assertIn("p.dominant_color AS dominant_color_1", connection.cursor_instance.executions[0][0])
        self.assertIn("p.palette_color_1 AS dominant_color_2", connection.cursor_instance.executions[0][0])

    def test_pin_card_returns_safe_not_found_for_missing_user_pin(self):
        """Returning a row-less card as success would leak pin existence."""
        with patch.object(app_module, "get_db_connection", return_value=FakeConnection([None])):
            response = self.client.get("/api/pin/42/card")
        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.get_json(), {"error": "Pin not found", "success": False})

    def test_update_pin_persists_supplied_image_url_for_current_user(self):
        """Ignoring image_url would leave an image replacement unsaved."""
        connection = FakeConnection([PIN, None])
        with patch.object(app_module, "get_db_connection", return_value=connection), \
             patch.object(app_module, "record_audit"):
            response = self.client.post(
                "/update-pin/42",
                json={"image_url": "/static/images/default_pin.png"},
                headers={"Authorization": "Bearer test-token"},
            )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json(), {"success": True, "pin_id": 42})
        update_query, update_params = connection.cursor_instance.executions[1]
        self.assertIn("UPDATE pins SET image_url = %s", update_query)
        self.assertEqual(update_params, ("/static/images/default_pin.png", 42, 7))
