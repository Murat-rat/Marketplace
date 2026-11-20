import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend" / "layer" / "python"))

os.environ.setdefault("JWT_SECRET", "test-secret-that-is-long-enough-1234567890")
