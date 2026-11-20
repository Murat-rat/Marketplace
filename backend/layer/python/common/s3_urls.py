"""Turn the value stored in product_images.url into a URL the app can download.

product_images.url stores an S3 object KEY (e.g. "products/12/ab12.jpg"),
never a full URL chosen by a user. For each response the Lambda creates a
short-lived pre-signed GET URL, so the bucket can stay fully private and
links stop working shortly after they are handed out.

Signing happens locally (no network call), so it works from inside the VPC.
boto3 is already included in the Lambda Python runtime.

Environment:
    IMAGES_BUCKET   name of the private S3 bucket (optional until images exist)
"""

import os

_EXPIRES_SECONDS = 3600
_client = None


def _s3():
    global _client
    if _client is None:
        import boto3  # imported lazily: only needed when images exist
        _client = boto3.client("s3")
    return _client


def image_url(stored: str | None) -> str | None:
    if not stored:
        return None
    # Seed/demo rows may hold a full https URL; user uploads never do.
    if stored.startswith("https://"):
        return stored
    bucket = os.environ.get("IMAGES_BUCKET")
    if not bucket:
        return None
    return _s3().generate_presigned_url(
        "get_object", Params={"Bucket": bucket, "Key": stored}, ExpiresIn=_EXPIRES_SECONDS
    )
