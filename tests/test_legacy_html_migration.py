import json
import unittest

import migrate


class FakeMigrationCursor:
    def __init__(self, rows=None, applied=False):
        self.rows = rows or {}
        self.applied = applied
        self.current = None
        self.executions = []

    def execute(self, query, params=()):
        compact = " ".join(query.split())
        self.executions.append((compact, params))

        if "information_schema.tables" in compact:
            self.current = (1 if params[0] in self.rows else 0,)
        elif compact.startswith("SELECT 1 FROM schema_migrations"):
            self.current = (1,) if self.applied else None
        elif compact.startswith("SELECT ") and " FROM " in compact:
            table = compact.rsplit(" FROM ", 1)[1]
            self.current = self.rows.get(table, [])
        else:
            self.current = None

    def fetchone(self):
        return self.current

    def fetchall(self):
        return self.current or []


class LegacyHtmlMigrationTests(unittest.TestCase):
    def test_decoder_restores_repeated_legacy_escaping(self):
        """Decoding only one layer would leave repeatedly edited legacy text broken."""
        self.assertEqual(
            migrate.decode_legacy_html_entities("Artist&amp;#x27;s &amp;amp; studio"),
            "Artist's & studio",
        )
        self.assertEqual(migrate.decode_legacy_html_entities("Use &amp;copy; literally"),
                         "Use &copy; literally")

    def test_migration_normalizes_all_user_visible_text_shapes(self):
        """Omitting a text column would leave HTML entities visible in that frontend path."""
        audit_before = json.dumps({"title": "Artist&#x27;s pin"})
        cursor = FakeMigrationCursor(rows={
            "boards": [(1, "Artist&#x27;s board")],
            "sections": [(2, "Artist&amp;#x27;s section")],
            "pins": [(3, "Artist&#x27;s pin", "A &amp; B", "Use &lt;canvas&gt;")],
            "audit_log": [(4, "owner&#x27;s@example.test", audit_before, None, None)],
        })

        changed = migrate.migrate_legacy_html_entities(cursor)

        updates = [(query, params) for query, params in cursor.executions if query.startswith("UPDATE ")]
        self.assertEqual(changed, 4)
        self.assertIn(("UPDATE boards SET name = %s WHERE id = %s", ("Artist's board", 1)), updates)
        self.assertIn(("UPDATE sections SET name = %s WHERE id = %s", ("Artist's section", 2)), updates)
        self.assertIn((
            "UPDATE pins SET title = %s, description = %s, notes = %s WHERE id = %s",
            ("Artist's pin", "A & B", "Use <canvas>", 3),
        ), updates)
        audit_update = next(item for item in updates if item[0].startswith("UPDATE audit_log"))
        self.assertEqual(audit_update[1][0], "owner's@example.test")
        self.assertEqual(json.loads(audit_update[1][1]), {"title": "Artist's pin"})
        self.assertTrue(any(query.startswith("INSERT INTO schema_migrations")
                            for query, _params in cursor.executions))

    def test_migration_does_not_redecode_new_plain_text_on_later_starts(self):
        """Re-running startup must not reinterpret newly entered literal entity text."""
        cursor = FakeMigrationCursor(rows={"pins": []}, applied=True)

        changed = migrate.migrate_legacy_html_entities(cursor)

        self.assertEqual(changed, 0)
        self.assertFalse(any(query.startswith("UPDATE ") for query, _params in cursor.executions))


if __name__ == "__main__":
    unittest.main()
