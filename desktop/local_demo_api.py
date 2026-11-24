"""DEVELOPMENT ONLY: in-memory API substitute for trying the desktop UI offline.

Enabled with LOCAL_DEMO=1. It accepts any email/password because there is no
server and no real data: it never contacts the API, AWS or a database, and
everything disappears when the app closes. It is not a way into real
accounts; the real login is always checked by the auth Lambda. The window
title says "Local demo" so this mode cannot be mistaken for the real app.
"""

from decimal import Decimal

from api_client import ApiError
from session import Session


_CATEGORIES = [
    {"id": 1, "parent_category_id": None, "name": "Electronics"},
    {"id": 2, "parent_category_id": 1, "name": "Phones"},
    {"id": 3, "parent_category_id": 1, "name": "Laptops"},
    {"id": 4, "parent_category_id": None, "name": "Home"},
    {"id": 5, "parent_category_id": 4, "name": "Kitchen"},
    {"id": 6, "parent_category_id": None, "name": "Books"},
    {"id": 7, "parent_category_id": 6, "name": "Programming"},
    {"id": 8, "parent_category_id": None, "name": "Sports"},
    {"id": 9, "parent_category_id": 8, "name": "Fitness"},
]

_PRODUCTS = [
    {"id": 1, "name": "Nova X5 Smartphone", "description": "128 GB storage and a dual camera.",
     "price": "6499.00", "stock": 12, "average_rating": "4.6", "review_count": 18,
     "category_id": 2, "store_name": "Demo Store"},
    {"id": 2, "name": "Nova Lite Smartphone", "description": "An affordable phone with a long-lasting battery.",
     "price": "3299.00", "stock": 0, "average_rating": "4.1", "review_count": 9,
     "category_id": 2, "store_name": "Demo Store"},
    {"id": 3, "name": "AirBook 14 Laptop", "description": "16 GB RAM and a 512 GB SSD.",
     "price": "15999.00", "stock": 5, "average_rating": "4.8", "review_count": 11,
     "category_id": 3, "store_name": "Demo Store"},
    {"id": 4, "name": "Wireless Headphones", "description": "Noise cancelling with 30 hours of battery.",
     "price": "2199.00", "stock": 20, "average_rating": "4.4", "review_count": 23,
     "category_id": 1, "store_name": "Audio House"},
    {"id": 5, "name": "Coffee Maker", "description": "Programmable 12-cup coffee maker.",
     "price": "1299.00", "stock": 8, "average_rating": "4.2", "review_count": 7,
     "category_id": 5, "store_name": "Home Shop"},
    {"id": 6, "name": "Python for Beginners", "description": "A friendly introduction to programming.",
     "price": "459.00", "stock": 25, "average_rating": "4.9", "review_count": 31,
     "category_id": 7, "store_name": "Book Corner"},
    {"id": 7, "name": "Adjustable Dumbbell Pair", "description": "Quick-change weights for home workouts.",
     "price": "4299.00", "stock": 3, "average_rating": "4.5", "review_count": 12,
     "category_id": 9, "store_name": "Active Life"},
]


class LocalDemoApi:
    """Implements the desktop API methods without network or persistent storage."""

    def __init__(self, session: Session):
        self.session = session
        self._next_user_id = 1
        self._users_by_email: dict[str, dict] = {}
        self._carts: dict[int, dict[int, int]] = {}

    def login(self, email: str, password: str) -> None:
        user = self._users_by_email.get(email.lower())
        if user is None:
            name = email.split("@", 1)[0].replace(".", " ").title() or "Demo User"
            user = self._make_user(name, email, None)
        self.session.start("local-demo-token", 3600, user)

    def register(self, *, name: str, email: str, password: str, account_type: str,
                 phone: str | None = None, store_name: str | None = None,
                 store_description: str | None = None) -> None:
        seller_id = self._next_user_id if account_type == "seller" else None
        user = self._make_user(name, email, seller_id)
        self.session.start("local-demo-token", 3600, user)

    def logout(self) -> None:
        self.session.clear()

    def change_email(self, email: str) -> dict:
        user_id = self._require_session()
        email = email.strip().lower()
        existing = self._users_by_email.get(email)
        if existing is not None and int(existing["id"]) != user_id:
            raise ApiError(409, "conflict", "An account with this email already exists", "email")
        current = self.session.user
        old_email = current.email.lower()
        user = self._users_by_email.pop(old_email, None)
        if user is None:
            user = {"id": user_id, "name": current.name, "role": current.role,
                    "seller_id": current.seller_id}
        user["email"] = email
        self._users_by_email[email] = user
        return {"email": email}

    def change_password(self, current_password: str, new_password: str) -> dict:
        # Local demo mode has no real credentials; the form is exercised without
        # contacting an API or storing a password. The real Lambda verifies scrypt.
        self._require_session()
        return {"password_changed": True}

    def get_categories(self) -> list[dict]:
        self._require_session()
        return [dict(category) for category in _CATEGORIES]

    def search_products(self, *, q: str = "", category_id: int | None = None, sort: str = "newest",
                        in_stock: bool = False, page: int = 1, page_size: int = 20) -> dict:
        self._require_session()
        products = [product for product in _PRODUCTS if q.strip().lower() in
                    f"{product['name']} {product['description']}".lower()]
        if category_id is not None:
            category_ids = {category_id}
            changed = True
            while changed:
                changed = False
                for category in _CATEGORIES:
                    if category["parent_category_id"] in category_ids and category["id"] not in category_ids:
                        category_ids.add(category["id"])
                        changed = True
            products = [product for product in products if product["category_id"] in category_ids]
        if in_stock:
            products = [product for product in products if product["stock"] > 0]

        if sort == "price_asc":
            products.sort(key=lambda product: (Decimal(product["price"]), product["id"]))
        elif sort == "price_desc":
            products.sort(key=lambda product: (-Decimal(product["price"]), -product["id"]))
        elif sort == "rating":
            products.sort(key=lambda product: (-Decimal(product["average_rating"]),
                                               -product["review_count"], -product["id"]))
        else:
            products.sort(key=lambda product: product["id"], reverse=True)

        total = len(products)
        pages = max(1, (total + page_size - 1) // page_size)
        start = (page - 1) * page_size
        items = [self._summary(product) for product in products[start:start + page_size]]
        return {"items": items, "page": page, "page_size": page_size,
                "total": total, "pages": pages}

    def get_product(self, product_id: int) -> dict:
        self._require_session()
        product = self._find_product(product_id)
        if product is None:
            raise ApiError(404, "not_found", "This product does not exist or is no longer available")
        category_path = []
        category_id = product["category_id"]
        while category_id is not None:
            category = next((item for item in _CATEGORIES if item["id"] == category_id), None)
            if category is None:
                break
            category_path.append({"id": category["id"], "name": category["name"]})
            category_id = category["parent_category_id"]
        category_path.reverse()
        return {
            **self._summary(product),
            "description": product["description"],
            "published_at": None,
            "category_path": category_path,
            "seller": {"id": 1, "store_name": product["store_name"], "description": "Demo seller"},
            "images": [],
        }

    def get_cart(self) -> dict:
        user_id = self._require_session()
        cart = self._carts.setdefault(user_id, {})
        items = []
        subtotal = Decimal("0.00")
        total_quantity = 0
        for product_id, quantity in sorted(cart.items()):
            product = self._find_product(product_id)
            if product is None:
                continue
            price = Decimal(product["price"])
            line_total = price * quantity
            subtotal += line_total
            total_quantity += quantity
            items.append({
                "product_id": product_id,
                "name": product["name"],
                "unit_price": str(price),
                "quantity": quantity,
                "stock": product["stock"],
                "available": product["stock"] > 0 and quantity <= product["stock"],
                "line_total": str(line_total),
            })
        return {"items": items, "subtotal": str(subtotal),
                "total_quantity": total_quantity, "item_count": len(items)}

    def add_to_cart(self, product_id: int) -> dict:
        user_id = self._require_session()
        product = self._find_product(product_id)
        if product is None:
            raise ApiError(404, "not_found", "Product not found")
        cart = self._carts.setdefault(user_id, {})
        quantity = cart.get(product_id, 0)
        if product["stock"] <= quantity:
            raise ApiError(409, "conflict", "You cannot add more than the available stock")
        cart[product_id] = quantity + 1
        return {"product_id": product_id, "quantity": quantity + 1}

    def set_cart_quantity(self, product_id: int, quantity: int) -> dict:
        user_id = self._require_session()
        cart = self._carts.setdefault(user_id, {})
        if quantity <= 0:
            cart.pop(product_id, None)
            return {"product_id": product_id, "quantity": 0}
        product = self._find_product(product_id)
        if product is None or product_id not in cart:
            raise ApiError(404, "not_found", "This product is not in your cart")
        if quantity > product["stock"]:
            raise ApiError(409, "conflict", "The requested quantity exceeds available stock")
        cart[product_id] = quantity
        return {"product_id": product_id, "quantity": quantity}

    def remove_cart_item(self, product_id: int) -> dict:
        user_id = self._require_session()
        self._carts.setdefault(user_id, {}).pop(product_id, None)
        return {"product_id": product_id, "removed": True}

    def _require_session(self) -> int:
        if not self.session.active or self.session.user is None:
            raise ApiError(401, "unauthorized", "Your session has expired. Please sign in again.")
        return self.session.user.id

    def _make_user(self, name: str, email: str, seller_id: int | None) -> dict:
        user = {"id": self._next_user_id, "name": name, "email": email.lower(),
                "role": "buyer", "seller_id": seller_id}
        self._next_user_id += 1
        self._users_by_email[user["email"]] = user
        return user

    @staticmethod
    def _find_product(product_id: int) -> dict | None:
        return next((product for product in _PRODUCTS if product["id"] == int(product_id)), None)

    @staticmethod
    def _summary(product: dict) -> dict:
        return {
            "id": product["id"],
            "name": product["name"],
            "price": product["price"],
            "available": product["stock"] > 0,
            "stock": product["stock"],
            "average_rating": product["average_rating"],
            "review_count": product["review_count"],
            "category_id": product["category_id"],
            "seller": {"id": 1, "store_name": product["store_name"]},
            "image_url": None,
        }
