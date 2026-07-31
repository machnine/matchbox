"""Static asset paths and content fingerprints."""

from functools import lru_cache
from hashlib import sha256
from pathlib import Path

STATIC_DIR = Path(__file__).resolve().parent.parent / "static"


@lru_cache(maxsize=None)
def asset_version(path: str) -> str:
    """Return a stable fingerprint that changes when a static asset changes."""
    relative_path = Path(path)
    if relative_path.is_absolute() or ".." in relative_path.parts:
        raise ValueError("Static asset paths must stay within the static directory")

    return sha256((STATIC_DIR / relative_path).read_bytes()).hexdigest()[:16]
