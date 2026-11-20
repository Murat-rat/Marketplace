"""SQL for the auth Lambda. Every query uses %s placeholders (no string building)."""

# ---------- RDS #1 (core) ----------

def find_user_by_email(cur, email: str) -> dict | None:
    cur.execute(
        "SELECT id, name, email, phone, role, is_active FROM users WHERE email = %s",
        (email,),
    )
    return cur.fetchone()


def insert_user(cur, *, name: str, email: str, phone: str, role: str, created_at) -> int:
    cur.execute(
        "INSERT INTO users (name, email, phone, role, is_active, created_at) "
        "VALUES (%s, %s, %s, %s, TRUE, %s)",
        (name, email, phone, role, created_at),
    )
    return cur.lastrowid


def insert_seller(cur, *, user_id: int, store_name: str, description: str | None, created_at) -> int:
    cur.execute(
        "INSERT INTO sellers (user_id, store_name, description, is_active, created_at) "
        "VALUES (%s, %s, %s, TRUE, %s)",
        (user_id, store_name, description, created_at),
    )
    return cur.lastrowid


def find_active_seller_id(cur, user_id: int) -> int | None:
    """A user is a seller when they have an active row in `sellers`."""
    cur.execute("SELECT id FROM sellers WHERE user_id = %s AND is_active = TRUE", (user_id,))
    row = cur.fetchone()
    return row["id"] if row else None


# ---------- RDS #2 (secure) ----------

def insert_credentials(cur, *, user_id: int, password_hash: str) -> None:
    cur.execute(
        "INSERT INTO credentials (user_id, password_hash, failed_attempts, last_login) "
        "VALUES (%s, %s, 0, NULL)",
        (user_id, password_hash),
    )


def delete_credentials(cur, user_id: int) -> None:
    cur.execute("DELETE FROM credentials WHERE user_id = %s", (user_id,))


def get_credentials(cur, user_id: int) -> dict | None:
    cur.execute(
        "SELECT password_hash, failed_attempts, locked_until FROM credentials WHERE user_id = %s",
        (user_id,),
    )
    return cur.fetchone()


def register_failed_attempt(cur, user_id: int, *, max_attempts: int, lock_until) -> None:
    """Count a wrong password; on reaching max_attempts, lock and reset the counter.

    Done in ONE atomic UPDATE so concurrent wrong guesses cannot slip past the
    limit. MySQL evaluates SET assignments left to right, so locked_until must
    be computed BEFORE failed_attempts is overwritten.
    """
    cur.execute(
        "UPDATE credentials SET "
        "  locked_until    = IF(failed_attempts + 1 >= %s, %s, locked_until), "
        "  failed_attempts = IF(failed_attempts + 1 >= %s, 0, failed_attempts + 1) "
        "WHERE user_id = %s",
        (max_attempts, lock_until, max_attempts, user_id),
    )


def register_successful_login(cur, user_id: int, now) -> None:
    cur.execute(
        "UPDATE credentials SET failed_attempts = 0, locked_until = NULL, last_login = %s WHERE user_id = %s",
        (now, user_id),
    )
