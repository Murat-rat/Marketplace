"""MySQL connections for the two RDS instances.

Each Lambda receives ONLY the credentials of its own least-privilege MySQL
user through environment variables:

    CORE_DB_HOST, CORE_DB_NAME, CORE_DB_USER, CORE_DB_PASSWORD
    SECURE_DB_HOST, SECURE_DB_NAME, SECURE_DB_USER, SECURE_DB_PASSWORD
    DB_PORT          (optional, default 3306)
    DB_SSL_CA        (optional, path to the RDS CA bundle for TLS)

A Lambda that has no SECURE_* variables simply cannot connect to RDS #2.

Connections are cached at module level so they are reused across warm
invocations, and re-checked with ping() before each use.

All SQL in this project MUST use %s placeholders with a params tuple.
Never build SQL with f-strings or string concatenation.
"""

import os
from contextlib import contextmanager

import pymysql
import pymysql.cursors

CORE = "CORE"
SECURE = "SECURE"

_connections: dict[str, pymysql.connections.Connection] = {}


def _connect(prefix: str) -> pymysql.connections.Connection:
    try:
        host = os.environ[f"{prefix}_DB_HOST"]
        user = os.environ[f"{prefix}_DB_USER"]
        password = os.environ[f"{prefix}_DB_PASSWORD"]
        database = os.environ[f"{prefix}_DB_NAME"]
    except KeyError as missing:
        raise RuntimeError(f"Database {prefix} is not configured for this function: {missing}") from None

    kwargs = dict(
        host=host,
        user=user,
        password=password,
        database=database,
        port=int(os.environ.get("DB_PORT", "3306")),
        charset="utf8mb4",
        cursorclass=pymysql.cursors.DictCursor,
        autocommit=False,
        connect_timeout=5,
        read_timeout=10,
        write_timeout=10,
    )
    ca = os.environ.get("DB_SSL_CA")
    if ca:
        kwargs["ssl"] = {"ca": ca}
    return pymysql.connect(**kwargs)


def get_connection(prefix: str) -> pymysql.connections.Connection:
    conn = _connections.get(prefix)
    if conn is None:
        conn = _connect(prefix)
        _connections[prefix] = conn
    else:
        conn.ping(reconnect=True)
    return conn


@contextmanager
def transaction(prefix: str):
    """Yield a cursor inside a transaction: commit on success, rollback on any error."""
    conn = get_connection(prefix)
    cursor = conn.cursor()
    try:
        yield cursor
        conn.commit()
    except BaseException:
        conn.rollback()
        raise
    finally:
        cursor.close()


@contextmanager
def open_transaction(prefix: str):
    """Like transaction(), but the caller decides when to commit.

    Used by flows that span two databases (e.g. register, checkout): the
    first database's transaction stays open until the second one succeeds.
    Yields (connection, cursor). Rolls back automatically on error or if the
    caller exits without committing.
    """
    conn = get_connection(prefix)
    cursor = conn.cursor()
    try:
        yield conn, cursor
    finally:
        try:
            conn.rollback()  # no-op if the caller already committed
        finally:
            cursor.close()
