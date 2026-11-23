"""Image upload script: file checks, S3 keys and the generated SQL (no AWS needed)."""

import importlib.util
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "backend" / "images" / "upload_images.py"
spec = importlib.util.spec_from_file_location("upload_images", SCRIPT)
up = importlib.util.module_from_spec(spec)
spec.loader.exec_module(up)

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 32
JPG = b"\xff\xd8\xff\xe0" + b"\x00" * 32
WEBP = b"RIFF\x24\x00\x00\x00WEBPVP8 " + b"\x00" * 32


def write(folder, name, data):
    path = folder / name
    path.write_bytes(data)
    return path


@pytest.mark.parametrize("name, data, content_type", [
    ("Phones.png", PNG, "image/png"), ("Laptops.jpg", JPG, "image/jpeg"),
    ("Audio.JPEG", JPG, "image/jpeg"), ("Home.webp", WEBP, "image/webp"),
])
def test_accepts_real_images(tmp_path, name, data, content_type):
    assert up.check_image(write(tmp_path, name, data)) == content_type


@pytest.mark.parametrize("name, data", [
    ("Phones.jpg", b"<script>alert(1)</script>"),   # renamed text file
    ("Phones.png", JPG),                            # wrong format for the extension
    ("Phones.gif", b"GIF89a" + b"\x00" * 10),       # format not accepted
    ("Phones.svg", b"<svg></svg>"),                 # SVG can carry scripts
    ("Phones.exe", b"MZ" + b"\x00" * 10),
    ("Phones.png", b""),
])
def test_rejects_fake_or_unsupported_files(tmp_path, name, data):
    with pytest.raises(up.ImageError):
        up.check_image(write(tmp_path, name, data))


def test_rejects_files_over_5_mb(tmp_path):
    with pytest.raises(up.ImageError):
        up.check_image(write(tmp_path, "Big.png", PNG + b"\x00" * (5 * 1024 * 1024)))


@pytest.mark.parametrize("filename, category", [
    ("Phones.jpg", "Phones"), ("cycling.png", "cycling"), ("Office_Chairs.jpg", "Office Chairs"),
    ("home-decor.webp", "home decor"),
])
def test_category_from_filename(filename, category):
    assert up.category_from_filename(Path(filename)) == category


@pytest.mark.parametrize("filename", ["x'; DROP TABLE products; --.jpg", "Phones%.jpg", "a" * 60 + ".jpg",
                                      "Teléfonos.jpg"])
def test_rejects_unsafe_category_names(filename):
    with pytest.raises(up.ImageError):
        up.category_from_filename(Path(filename))


def test_key_is_random_and_hides_the_original_name():
    a = up.make_key("Office Chairs", Path("my secret photo.jpeg"))
    b = up.make_key("Office Chairs", Path("my secret photo.jpeg"))
    assert a != b
    assert a.startswith("catalog/office-chairs/") and a.endswith(".jpg")
    assert "secret" not in a and len(a) < 255  # fits product_images.url


def test_collect_reports_every_problem_and_duplicates(tmp_path):
    write(tmp_path, "Phones.jpg", JPG)
    write(tmp_path, "phones.png", PNG)          # same category twice
    write(tmp_path, "Laptops.jpg", b"not an image")
    with pytest.raises(up.ImageError) as err:
        up.collect(tmp_path)
    assert "phones.png" in str(err.value) and "Laptops.jpg" in str(err.value)


def test_collect_ok(tmp_path):
    write(tmp_path, "Phones.jpg", JPG)
    write(tmp_path, "Home.png", PNG)
    write(tmp_path, ".DS_Store", b"x")          # hidden files are ignored
    assert [c for _, c, _ in up.collect(tmp_path)] == ["Home", "Phones"]


def test_sql_specific_category_wins_and_is_rerunnable():
    sql = up.build_sql([("Home", "catalog/home/a.png"), ("Kitchen", "catalog/kitchen/b.jpg")])
    own = sql.index("WHERE c.name = 'Kitchen'")
    parent = sql.index("WHERE parent.name = 'Home'")
    assert own < parent                          # Kitchen.jpg beats Home.png for kitchen products
    assert sql.count("NOT EXISTS (SELECT 1 FROM product_images pi WHERE pi.product_id = p.id)") == 4
    assert "START TRANSACTION;" in sql and "COMMIT;" in sql


def test_sql_quotes_values():
    sql = up.build_sql([("O'Brien", "catalog/x/a.jpg")])  # cannot come from a file name, still safe
    assert "'O''Brien'" in sql
