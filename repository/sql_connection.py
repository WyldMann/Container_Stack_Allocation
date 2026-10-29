"""One caller-owned, read-only PostgreSQL snapshot for input acquisition."""

from contextlib import contextmanager
import os

from config import ConfigurationError


@contextmanager
def input_connection(settings, *, include_shifting=True):
    needs_sql = "sql" in settings["sources"].values() or (
        include_shifting and settings.get("shifting_source") == "sql"
    )
    if not needs_sql:
        yield None
        return
    try:
        import psycopg
    except ImportError as error:
        raise ConfigurationError(
            "SQL input requires Psycopg 3. Install requirements-sql.txt."
        ) from error
    options = dict(settings["connection"])
    password_env = settings["password_env"]
    if password_env:
        password = os.environ.get(password_env)
        if password is None:
            raise ConfigurationError(f"SQL password environment variable {password_env!r} is not set.")
        options["password"] = password
    with psycopg.connect(**options) as connection:
        connection.read_only = True
        connection.isolation_level = (
            psycopg.IsolationLevel.REPEATABLE_READ
            if settings["consistent_snapshot"] else psycopg.IsolationLevel.READ_COMMITTED
        )
        yield connection
