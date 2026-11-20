"""Read-only SQL for the catalog Lambda (MySQL user app_catalog: SELECT only).

Only active products of active sellers in active categories are ever shown.
Every value goes through %s placeholders; the only SQL fragments chosen in
code (ORDER BY, search mode) come from fixed whitelists, never from input.
"""

# Category ids of `category_id` and all its active descendants.
_CATEGORY_TREE_CTE = """
WITH RECURSIVE tree AS (
    SELECT id FROM categories WHERE id = %s AND is_active = TRUE
    UNION ALL
    SELECT c.id FROM categories c JOIN tree t ON c.parent_category_id = t.id
    WHERE c.is_active = TRUE
)
"""

_VISIBLE = """
    p.is_active = TRUE
    AND s.is_active = TRUE
    AND cat.is_active = TRUE
"""

ORDER_BY = {
    "newest": "p.published_at DESC, p.id DESC",
    "price_asc": "p.price ASC, p.id ASC",
    "price_desc": "p.price DESC, p.id DESC",
    "rating": "p.average_rating DESC, p.review_count DESC, p.id DESC",
}


def list_categories(cur) -> list[dict]:
    cur.execute(
        "SELECT id, parent_category_id, name FROM categories WHERE is_active = TRUE ORDER BY name"
    )
    return cur.fetchall()


def search_products(cur, *, fulltext: str | None, like: str | None, category_id: int | None,
                    in_stock: bool, sort: str, limit: int, offset: int) -> tuple[int, list[dict]]:
    where = [_VISIBLE]
    params: list = []
    prefix = ""
    if category_id is not None:
        prefix = _CATEGORY_TREE_CTE
        params.append(category_id)
        where.append("p.category_id IN (SELECT id FROM tree)")
    if fulltext:
        where.append("MATCH(p.name, p.description) AGAINST (%s IN BOOLEAN MODE)")
        params.append(fulltext)
    elif like:
        where.append("p.name LIKE %s ESCAPE '\\\\'")
        params.append(like)
    if in_stock:
        where.append("p.stock > 0")

    base = f"""
        FROM products p
        JOIN sellers s ON s.id = p.seller_id
        JOIN categories cat ON cat.id = p.category_id
        WHERE {' AND '.join(where)}
    """

    cur.execute(prefix + "SELECT COUNT(*) AS total " + base, tuple(params))
    total = cur.fetchone()["total"]

    cur.execute(
        prefix
        + """SELECT p.id, p.name, p.price, p.stock, p.average_rating, p.review_count,
                    p.category_id, s.id AS seller_id, s.store_name,
                    (SELECT pi.url FROM product_images pi
                      WHERE pi.product_id = p.id
                      ORDER BY pi.is_primary DESC, pi.sort_order ASC, pi.id ASC
                      LIMIT 1) AS image
           """
        + base
        + f" ORDER BY {ORDER_BY[sort]} LIMIT %s OFFSET %s",
        tuple(params) + (limit, offset),
    )
    return total, cur.fetchall()


def get_product(cur, product_id: int) -> dict | None:
    cur.execute(
        f"""SELECT p.id, p.name, p.description, p.price, p.stock, p.average_rating,
                   p.review_count, p.published_at, p.category_id,
                   s.id AS seller_id, s.store_name, s.description AS store_description
            FROM products p
            JOIN sellers s ON s.id = p.seller_id
            JOIN categories cat ON cat.id = p.category_id
            WHERE p.id = %s AND {_VISIBLE}""",
        (product_id,),
    )
    return cur.fetchone()


def get_images(cur, product_id: int) -> list[dict]:
    cur.execute(
        "SELECT url FROM product_images WHERE product_id = %s "
        "ORDER BY is_primary DESC, sort_order ASC, id ASC",
        (product_id,),
    )
    return cur.fetchall()


def get_category_path(cur, category_id: int) -> list[dict]:
    """Breadcrumb from the root category down to `category_id`."""
    cur.execute(
        """WITH RECURSIVE path AS (
               SELECT id, parent_category_id, name, 0 AS depth FROM categories WHERE id = %s
               UNION ALL
               SELECT c.id, c.parent_category_id, c.name, p.depth + 1
               FROM categories c JOIN path p ON c.id = p.parent_category_id
               WHERE p.depth < 20
           )
           SELECT id, name FROM path ORDER BY depth DESC""",
        (category_id,),
    )
    return cur.fetchall()
