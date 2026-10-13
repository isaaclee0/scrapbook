"""Small real-SQL adapter shared by gallery service and integration tests."""


class SqliteCursor:
    def __init__(self, connection, dictionaries=True):
        self.cursor = connection.cursor()
        self.dictionaries = dictionaries

    def execute(self, query, params=()):
        self.cursor.execute(query.replace('%s', '?').replace(' FOR UPDATE', ''), params)

    @property
    def description(self):
        return self.cursor.description

    @property
    def lastrowid(self):
        return self.cursor.lastrowid

    @property
    def rowcount(self):
        return self.cursor.rowcount

    def fetchone(self):
        row = self.cursor.fetchone()
        return self._row(row) if row is not None else None

    def fetchall(self):
        return [self._row(row) for row in self.cursor.fetchall()]

    def _row(self, row):
        return dict(zip((column[0] for column in self.description), row)) if self.dictionaries else row

    def close(self):
        self.cursor.close()
