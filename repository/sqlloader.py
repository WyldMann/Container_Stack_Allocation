from contextlib import contextmanager

from .loader import InputError


class SQLLoader:
    """Read a query using a caller-owned Psycopg 3 connection.

    The caller owns transactions and connection closure. Share one connection
    across dataset loads when a consistent snapshot is required. Queries must
    bind values through parameters and quote identifiers with psycopg.sql.
    """

    def __init__(self, connection, query, *, parameters=None,
                 source="PostgreSQL query"):
        self.connection = connection
        self.query = query
        self.parameters = parameters
        self.source = source

    @contextmanager
    def open(self):
        # CSV-only installations do not need the PostgreSQL driver.
        from psycopg.rows import tuple_row

        with self.connection.cursor(row_factory=tuple_row) as cursor:
            cursor.execute(self.query, self.parameters)
            if cursor.description is None:
                raise InputError(f"{self.source}: query returned no columns.")
            headers = [column.name for column in cursor.description]

            def iter_rows():
                for number, values in enumerate(cursor, start=1):
                    yield (
                        f"{self.source}, result row {number}",
                        dict(zip(headers, values, strict=True)),
                    )

            yield headers, iter_rows()
