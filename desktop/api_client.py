"""The only place the desktop app talks to the backend.

Every call returns parsed JSON or raises ApiError with a message that is
safe to show to the user.
"""

import requests

from session import Session

TIMEOUT_SECONDS = 20
MAX_IMAGE_BYTES = 5 * 1024 * 1024


class ApiError(Exception):
    def __init__(self, status: int, code: str, message: str, field: str | None = None):
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message
        self.field = field

    @property
    def session_expired(self) -> bool:
        return self.status == 401 and self.code == "unauthorized"


class ApiClient:
    def __init__(self, base_url: str, session: Session):
        self.base_url = base_url
        self.session = session
        self._http = requests.Session()
        self._http.headers.update({"Accept": "application/json", "User-Agent": "MarketplaceDesktop/0.1"})
        # Images come from S3, not from our API: a separate session that
        # never carries the login token.
        self._images = requests.Session()

    # ------------------------------------------------------------ core

    def _request(self, method: str, path: str, body: dict | None = None, auth: bool = True,
                 params: dict | None = None) -> dict:
        headers = {}
        if auth:
            token = self.session.token
            if token is None:
                raise ApiError(401, "unauthorized", "Your session has expired. Please sign in again.")
            headers["Authorization"] = f"Bearer {token}"
        try:
            resp = self._http.request(
                method, self.base_url + path, json=body, headers=headers, timeout=TIMEOUT_SECONDS,
                params=params,
            )
        except requests.Timeout:
            raise ApiError(0, "network", "The server took too long to answer. Try again.") from None
        except requests.RequestException:
            raise ApiError(0, "network", "Could not reach the server. Check your internet connection.") from None

        try:
            data = resp.json()
        except ValueError:
            data = {}

        if resp.ok:
            return data
        if resp.status_code == 429:
            raise ApiError(429, "throttled", "Too many attempts. Wait a moment and try again.")
        raise ApiError(
            resp.status_code,
            str(data.get("error", "error")),
            str(data.get("message", "Something went wrong. Try again later.")),
            data.get("field"),
        )

    # ------------------------------------------------------------ auth

    def login(self, email: str, password: str) -> None:
        data = self._request("POST", "/login", {"email": email, "password": password}, auth=False)
        self.session.start(data["token"], data["expires_in"], data["user"])

    def register(self, *, name: str, email: str, password: str, account_type: str,
                 phone: str | None = None, store_name: str | None = None,
                 store_description: str | None = None) -> None:
        body = {"name": name, "email": email, "password": password, "account_type": account_type}
        if phone:
            body["phone"] = phone
        if account_type == "seller":
            body["store_name"] = store_name
            if store_description:
                body["store_description"] = store_description
        data = self._request("POST", "/register", body, auth=False)
        self.session.start(data["token"], data["expires_in"], data["user"])

    def logout(self) -> None:
        self.session.clear()

    # ------------------------------------------------------------ catalog

    def get_categories(self) -> list[dict]:
        return self._request("GET", "/categories")["categories"]

    def search_products(self, *, q: str = "", category_id: int | None = None, sort: str = "newest",
                        in_stock: bool = False, page: int = 1, page_size: int = 20) -> dict:
        params = {"sort": sort, "page": page, "page_size": page_size}
        if q.strip():
            params["q"] = q.strip()[:200]
        if category_id is not None:
            params["category_id"] = int(category_id)
        if in_stock:
            params["in_stock"] = 1
        return self._request("GET", "/products", params=params)

    def get_product(self, product_id: int) -> dict:
        return self._request("GET", f"/products/{int(product_id)}")

    def download_image(self, url: str) -> bytes:
        """Fetch an image (HTTPS only, at most 5 MB, must really be an image)."""
        if not url.startswith("https://"):
            raise ApiError(0, "image", "Image URL is not secure")
        try:
            with self._images.get(url, timeout=TIMEOUT_SECONDS, stream=True) as resp:
                if not resp.ok or not resp.headers.get("Content-Type", "").startswith("image/"):
                    raise ApiError(resp.status_code, "image", "Image not available")
                data = bytearray()
                for chunk in resp.iter_content(64 * 1024):
                    data.extend(chunk)
                    if len(data) > MAX_IMAGE_BYTES:
                        raise ApiError(0, "image", "Image is too large")
                return bytes(data)
        except requests.RequestException:
            raise ApiError(0, "network", "Could not download the image") from None
