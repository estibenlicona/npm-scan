import json
import hashlib
import os
from pathlib import Path
from typing import Any, Dict, Optional

import click

def _determine_cache_root() -> Path:
    override = os.getenv('NPM_SCAN_CACHE_ROOT')
    if override:
        return Path(override).expanduser()
    return Path(os.getcwd()) / '.npm_scan_cache'

CACHE_ROOT = _determine_cache_root()


def _ensure_root() -> None:
    CACHE_ROOT.mkdir(parents=True, exist_ok=True)


def cache_subdir(name: str) -> Path:
    _ensure_root()
    path = CACHE_ROOT / name
    path.mkdir(parents=True, exist_ok=True)
    return path


def signature_for_json(document: Any) -> str:
    """Return a deterministic SHA256 signature for JSON-serialisable data."""
    try:
        payload = json.dumps(document, sort_keys=True, separators=(",", ":"))
    except TypeError:
        payload = json.dumps(document, default=str, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def save_json_document(subdir: str, signature: str, document: Any) -> Path:
    """Persist the JSON document under the cache subdir using its signature."""
    path = cache_subdir(subdir) / f"{signature}.json"
    with path.open("w", encoding="utf-8") as handle:
        json.dump(document, handle, indent=2, ensure_ascii=False)
    return path


def load_json_document(subdir: str, signature: str) -> Optional[Any]:
    """Load a cached JSON document by signature if present."""
    path = cache_subdir(subdir) / f"{signature}.json"
    if not path.exists():
        return None
    try:
        with path.open("r", encoding="utf-8") as handle:
            return json.load(handle)
    except json.JSONDecodeError:
        return None


def document_path(subdir: str, signature: str) -> Path:
    """Return the path of the cached JSON document regardless of existence."""
    return cache_subdir(subdir) / f"{signature}.json"


def load_index(name: str) -> Dict[str, Any]:
    """Read an index JSON stored at the cache root."""
    _ensure_root()
    path = CACHE_ROOT / name
    click.echo(f"[Info]: path: {path}")
    if not path.exists():
        return {}
    try:
        with path.open("r", encoding="utf-8") as handle:
            return json.load(handle)
    except json.JSONDecodeError:
        return {}


def save_index(name: str, payload: Dict[str, Any]) -> Path:
    """Persist the index JSON, overwriting any previous payload."""
    _ensure_root()
    path = CACHE_ROOT / name
    with path.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2, ensure_ascii=False)
    return path


def build_repo_key(item: Dict[str, Any]) -> str:
    """Create a stable key that identifies the repo+branch+path tuple."""
    repo_id = (item.get("repository") or {}).get("id", "")
    path = item.get("path", "")
    branch = ""
    versions = item.get("versions") or []
    if versions:
        branch = versions[0].get("branchName", "")
    return f"{repo_id}|{branch}|{path}"
