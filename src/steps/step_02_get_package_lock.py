import os
import json
import hashlib
import pickle
import tempfile
import shutil
import subprocess
from typing import Any, Dict, Optional

# Caché de package-lock.json
CACHE_DIR = os.path.join(os.getcwd(), ".npm_scan_cache")
CACHE_FILE = os.path.join(CACHE_DIR, "package_lock_cache.pkl")


def generate_package_json_signature(package_json_content: Dict[str, Any]) -> str:
    """
    Genera una firma SHA256 determinista de package.json para usar como clave de caché.
    """
    json_string = json.dumps(package_json_content, sort_keys=True)
    return hashlib.sha256(json_string.encode('utf-8')).hexdigest()


def ensure_cache_directory() -> None:
    """Crea el directorio de caché si no existe."""
    if not os.path.exists(CACHE_DIR):
        os.makedirs(CACHE_DIR, exist_ok=True)


def load_cache() -> Dict[str, Any]:
    """Carga el dict de caché de package-locks, o {} si no existe."""
    try:
        if os.path.exists(CACHE_FILE):
            with open(CACHE_FILE, 'rb') as f:
                return pickle.load(f) or {}
    except (pickle.UnpicklingError, OSError):
        pass
    return {}


def save_cache(cache: Dict[str, Any]) -> None:
    """Guarda el dict de caché de package-locks."""
    ensure_cache_directory()
    with open(CACHE_FILE, 'wb') as f:
        pickle.dump(cache, f)


def get_cached_lock_content(signature: str) -> Optional[Dict[str, Any]]:
    """
    Retorna el package-lock.json completo de cache si existe, else None.
    """
    cache = load_cache()
    lock = cache.get(signature)
    if lock is not None:
        print(
            f"[Ok]: Cache package-lock.json: {signature[:8]}... -> {len(lock.get('packages', {}))} paquetes")
    return lock


def cache_lock_content(signature: str, lock_content: Dict[str, Any]) -> None:
    """
    Guarda el contenido completo de package-lock.json en cache.
    """
    cache = load_cache()
    cache[signature] = lock_content
    save_cache(cache)


def check_npm_available() -> bool:
    """Verifica si `npm` está en PATH."""
    try:
        result = subprocess.run(["npm", "--version"],
                                capture_output=True, text=True, timeout=10, check=False)
        return result.returncode == 0
    except (subprocess.SubprocessError, OSError, subprocess.TimeoutExpired):
        return False


def generate_package_lock(package_json_content: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """
    Genera o recupera de cache un package-lock.json usando npm install.
    Devuelve el JSON completo o None en fallo.
    """
    signature = generate_package_json_signature(package_json_content)
    # Intentar cache
    cached = get_cached_lock_content(signature)
    if cached is not None:
        return cached
    # Verificar npm
    if not check_npm_available():
        print("[Error]: npm no disponible, no se puede generar package-lock.json")
        return None
    temp_dir = tempfile.mkdtemp(prefix="npm_scan_")
    try:
        pkg_json_path = os.path.join(temp_dir, "package.json")
        lock_path = os.path.join(temp_dir, "package-lock.json")
        with open(pkg_json_path, 'w', encoding='utf-8') as f:
            json.dump(package_json_content, f, indent=2)
        result = subprocess.run([
            "npm", "install", "--package-lock-only", "--legacy-peer-deps", "--ignore-scripts", "--no-audit", "--no-fund"
        ], cwd=temp_dir, capture_output=True, text=True, timeout=120, check=False)
        if result.returncode == 0 and os.path.exists(lock_path):
            with open(lock_path, 'r', encoding='utf-8') as f:
                lock_content = json.load(f)
            cache_lock_content(signature, lock_content)
            return lock_content
        else:
            print(f"[Error]: Fallo npm install: {result.stderr}")
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)
    return None
