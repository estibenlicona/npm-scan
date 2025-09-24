import json
import copy
import os
import pickle
import shutil
import subprocess
import tempfile
from typing import Any, Dict, Optional, Tuple, List, Set

import click
import requests

try:
    from .cache_utils import (
        CACHE_ROOT,
        build_repo_key,
        load_index,
        load_json_document,
        save_index,
        save_json_document,
        signature_for_json,
    )
    from .step_01_get_repositories import ORG, auth, load_repos_cache
except ImportError:
    from cache_utils import (
        CACHE_ROOT,
        build_repo_key,
        load_index,
        load_json_document,
        save_index,
        save_json_document,
        signature_for_json,
    )
    from step_01_get_repositories import ORG, auth, load_repos_cache

PACKAGE_JSON_SUBDIR = "package_json"
PACKAGE_LOCK_SUBDIR = "package_lock"
PACKAGES_REPO_INDEX_FILE = "package_json_repo_index.json"
PACKAGE_LOCK_MANIFEST_FILE = "package_lock_manifest.json"
PACKAGE_LOCK_REPO_INDEX_FILE = "package_lock_repo_index.json"
LEGACY_LOCK_CACHE_FILE = CACHE_ROOT / "package_lock_cache.pkl"


def load_packages_repo_index() -> Dict[str, Dict[str, Any]]:
    index = load_index(PACKAGES_REPO_INDEX_FILE)
    if isinstance(index, dict):
        return index
    return {}


def migrate_legacy_lock_cache() -> Dict[str, Dict[str, Any]]:
    manifest: Dict[str, Dict[str, Any]] = {}
    if not LEGACY_LOCK_CACHE_FILE.exists():
        return manifest
    try:
        with LEGACY_LOCK_CACHE_FILE.open("rb") as handle:
            legacy_payload = pickle.load(handle)
    except (OSError, pickle.UnpicklingError):
        return manifest
    if not isinstance(legacy_payload, dict):
        return manifest
    for signature, lock_content in legacy_payload.items():
        if not isinstance(signature, str) or not isinstance(lock_content, dict):
            continue
        save_json_document(PACKAGE_LOCK_SUBDIR, signature, lock_content)
        manifest[signature] = {
            "path": f"{PACKAGE_LOCK_SUBDIR}/{signature}.json",
            "repos": [],
            "packageSignatures": [],
            "sources": ["legacy"],
        }
    return manifest


def load_lock_manifest() -> Dict[str, Dict[str, Any]]:
    manifest_raw = load_index(PACKAGE_LOCK_MANIFEST_FILE)
    if not isinstance(manifest_raw, dict):
        manifest_raw = {}
    manifest: Dict[str, Dict[str, Any]] = {}
    migrated = False
    for signature, payload in manifest_raw.items():
        if isinstance(payload, dict) and "path" in payload:
            sources = payload.get("sources")
            if isinstance(sources, list):
                source_list = sources
            else:
                single_source = payload.get("source")
                source_list = [single_source] if isinstance(single_source, str) else []
            manifest[signature] = {
                "path": payload.get("path", f"{PACKAGE_LOCK_SUBDIR}/{signature}.json"),
                "repos": payload.get("repos", []),
                "packageSignatures": payload.get("packageSignatures", []),
                "sources": source_list,
            }
            continue
        if isinstance(payload, dict):
            save_json_document(PACKAGE_LOCK_SUBDIR, signature, payload)
            manifest[signature] = {
                "path": f"{PACKAGE_LOCK_SUBDIR}/{signature}.json",
                "repos": [],
                "packageSignatures": [],
                "sources": ["migrated"],
            }
            migrated = True
    if not manifest:
        legacy_manifest = migrate_legacy_lock_cache()
        if legacy_manifest:
            manifest.update(legacy_manifest)
            migrated = True
    if migrated:
        save_index(PACKAGE_LOCK_MANIFEST_FILE, manifest)
    return manifest


def load_lock_repo_index() -> Dict[str, Dict[str, Any]]:
    index = load_index(PACKAGE_LOCK_REPO_INDEX_FILE)
    if isinstance(index, dict):
        return index
    return {}


def _build_package_to_lock_map(manifest: Dict[str, Dict[str, Any]]) -> Dict[str, Tuple[str, str]]:
    """Return mapping packageSignature -> (lockSignature, preferredSource).

    preferredSource resolves to 'repository' if present in sources, otherwise 'generated'.
    """
    mapping: Dict[str, Tuple[str, str]] = {}
    for lock_sig, entry in (manifest or {}).items():
        if not isinstance(entry, dict):
            continue
        pkg_sigs = entry.get("packageSignatures") or []
        if not isinstance(pkg_sigs, list):
            continue
        sources = entry.get("sources") or []
        src = "repository" if isinstance(sources, list) and "repository" in sources else "generated"
        for pkg_sig in pkg_sigs:
            if isinstance(pkg_sig, str) and pkg_sig and pkg_sig not in mapping:
                mapping[pkg_sig] = (lock_sig, src)
    return mapping


def lock_path_from_package_path(package_path: str) -> str:
    suffix = "package.json"
    lower_path = package_path.lower()
    if lower_path.endswith(suffix):
        return f"{package_path[:-len(suffix)]}package-lock.json"
    if package_path.endswith("/"):
        return f"{package_path}package-lock.json"
    return f"{package_path}/package-lock.json"


def fetch_package_lock_from_repo(item: Dict[str, Any]) -> Tuple[Optional[Any], Optional[str]]:
    project = item["project"]["name"]
    repo_id = item["repository"]["id"]
    versions = item.get("versions") or []
    branch = versions[0].get("branchName", "") if versions else ""
    lock_path = lock_path_from_package_path(item.get("path", ""))
    url = f"https://dev.azure.com/{ORG}/{project}/_apis/git/repositories/{repo_id}/items"
    params: Dict[str, Any] = {
        "path": lock_path,
        "includeContent": True,
        "versionDescriptor.version": branch,
        "api-version": "7.1",
    }
    resp = requests.get(url, auth=auth, params=params, timeout=10)
    if resp.status_code == 404:
        return None, "missing"
    resp.raise_for_status()
    return resp.json(), None


def check_npm_available() -> bool:
    try:
        result = subprocess.run(
            ["npm", "--version"],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
        return result.returncode == 0
    except (OSError, subprocess.SubprocessError, subprocess.TimeoutExpired):
        return False


def _get_private_scopes() -> Set[str]:
    scopes_raw = os.getenv("NPM_PRIVATE_SCOPES", "@appcross")
    scopes: Set[str] = set()
    for part in scopes_raw.split(","):
        s = part.strip()
        if s:
            if not s.startswith("@"):
                s = "@" + s
            scopes.add(s)
    return scopes


def _sanitize_package_json_for_fallback(content: Dict[str, Any]) -> Tuple[Dict[str, Any], List[str]]:
    msgs: List[str] = []
    effective = copy.deepcopy(content)

    # Remove workspaces (avoids EWORKSPACESCONFIG)
    if effective.pop("workspaces", None) is not None:
        msgs.append("[Warn] package.json contiene 'workspaces'; eliminado para generar lock de fallback")

    # Remove overrides to avoid EOVERRIDE conflicts
    if effective.pop("overrides", None) is not None:
        msgs.append("[Warn] package.json contiene 'overrides'; eliminado para evitar conflictos en fallback")

    private_scopes = _get_private_scopes()

    def should_drop_dep(name: str, spec: Any) -> Tuple[bool, Optional[str]]:
        if not isinstance(name, str):
            return True, None
        # Private scopes
        for scope in private_scopes:
            if name.startswith(scope + "/"):
                return True, "private"
        # Unresolvable specs in temp dir
        if isinstance(spec, str):
            s = spec.strip().lower()
            invalid_prefixes = (
                "file:",
                "link:",
                "workspace:",
                "git+",
                "github:",
                "http:",
                "https:",
            )
            if s.startswith(invalid_prefixes):
                return True, "local"
        return False, None

    removed_private: List[str] = []
    removed_local: List[str] = []
    for key in ("dependencies", "devDependencies", "peerDependencies", "optionalDependencies"):
        deps = effective.get(key)
        if not isinstance(deps, dict):
            continue
        to_delete: List[str] = []
        for dep_name, dep_spec in deps.items():
            drop, reason = should_drop_dep(dep_name, dep_spec)
            if drop:
                to_delete.append(dep_name)
                if reason == "private":
                    removed_private.append(dep_name)
                elif reason == "local":
                    removed_local.append(dep_name)
        for dep_name in to_delete:
            deps.pop(dep_name, None)
        if not deps:
            effective.pop(key, None)

    if removed_private:
        msgs.append(
            "[Warn] Dependencias de scopes privados omitidas en fallback: "
            + ", ".join(sorted(set(removed_private)))
        )
    if removed_local:
        msgs.append(
            "[Warn] Dependencias locales/git/url omitidas en fallback: "
            + ", ".join(sorted(set(removed_local)))
        )

    return effective, msgs


def generate_lock_with_npm(package_content: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    if not check_npm_available():
        click.echo("[Error] npm no disponible para generar package-lock.json")
        return None
    temp_dir = tempfile.mkdtemp(prefix="npm_scan_")
    try:
        package_path = os.path.join(temp_dir, "package.json")
        lock_path = os.path.join(temp_dir, "package-lock.json")
        effective_content = copy.deepcopy(package_content) if isinstance(package_content, dict) else package_content
        if isinstance(effective_content, dict):
            effective_content, _msgs = _sanitize_package_json_for_fallback(effective_content)
            for m in _msgs:
                click.echo(m)
        with open(package_path, "w", encoding="utf-8") as handle:
            json.dump(effective_content, handle, indent=2, ensure_ascii=False)
        env = os.environ.copy()
        env.setdefault("npm_config_cache", os.path.join(temp_dir, "npm-cache"))
        result = subprocess.run(
            [
                "npm",
                "install",
                "--package-lock-only",
                "--legacy-peer-deps",
                "--ignore-scripts",
                "--no-audit",
                "--no-fund",
                "--prefer-offline",
            ],
            cwd=temp_dir,
            capture_output=True,
            text=True,
            timeout=120,
            check=False,
            env=env,
        )
        if result.returncode != 0:
            click.echo(f"[Error] npm install fallo generando package-lock: {result.stderr.strip()}")
            return None
        if not os.path.exists(lock_path):
            click.echo("[Error] npm no genero package-lock.json")
            return None
        with open(lock_path, "r", encoding="utf-8") as handle:
            return json.load(handle)
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)


def update_lock_manifest_entry(
    manifest: Dict[str, Dict[str, Any]],
    lock_signature: str,
    repo_key: str,
    package_signature: str,
    source: str,
) -> None:
    entry = manifest.get(
        lock_signature,
        {
            "path": f"{PACKAGE_LOCK_SUBDIR}/{lock_signature}.json",
            "repos": [],
            "packageSignatures": [],
            "sources": [],
        },
    )
    repos = set(entry.get("repos") or [])
    repos.add(repo_key)
    entry["repos"] = sorted(repos)

    packages = set(entry.get("packageSignatures") or [])
    packages.add(package_signature)
    entry["packageSignatures"] = sorted(packages)

    sources = set(entry.get("sources") or [])
    sources.add(source)
    entry["sources"] = sorted(sources)

    entry["path"] = f"{PACKAGE_LOCK_SUBDIR}/{lock_signature}.json"
    manifest[lock_signature] = entry


def build_lock_repo_metadata(
    item: Dict[str, Any],
    package_signature: str,
    lock_signature: str,
    source: str,
) -> Dict[str, Any]:
    versions = item.get("versions") or []
    branch = versions[0].get("branchName", "") if versions else ""
    return {
        "lockSignature": lock_signature,
        "packageSignature": package_signature,
        "source": source,
        "repositoryId": item["repository"]["id"],
        "repositoryName": item["repository"].get("name"),
        "project": item["project"].get("name"),
        "path": item.get("path"),
        "branch": branch,
    }


def get_package_lock(force: bool = False) -> None:
    repos = load_repos_cache()
    if not repos:
        raise click.ClickException("No se encontro cache de repositorios. Ejecuta step_01 primero o revisa las credenciales.")

    packages_repo_index = load_packages_repo_index()
    if not packages_repo_index:
        raise click.ClickException("No se encontro index de package.json. Ejecuta step_02 previamente.")

    manifest = load_lock_manifest()
    lock_repo_index = load_lock_repo_index()
    pkg_to_lock = _build_package_to_lock_map(manifest)

    reused = 0
    downloaded = 0
    generated = 0
    failures: Dict[str, int] = {}

    for item in repos:
        repo_key = build_repo_key(item)
        package_meta = packages_repo_index.get(repo_key)
        if not package_meta:
            failures["package_json_missing"] = failures.get("package_json_missing", 0) + 1
            click.echo(
                f"[Warn] package.json no cacheado para {item['repository']['name']} ({repo_key}). Ejecuta step_02."
            )
            continue
        package_signature = package_meta["signature"]

        lock_meta = lock_repo_index.get(repo_key) if isinstance(lock_repo_index, dict) else None
        cached_signature = lock_meta.get("lockSignature") if isinstance(lock_meta, dict) else None
        cached_package_signature = (
            lock_meta.get("packageSignature") if isinstance(lock_meta, dict) else None
        )

        if (
            not force
            and cached_signature
            and cached_package_signature == package_signature
            and load_json_document(PACKAGE_LOCK_SUBDIR, cached_signature) is not None
        ):
            reused += 1
            continue

        # Fast-path reuse by package signature (avoid network and npm) if possible
        if not force and package_signature in pkg_to_lock:
            mapped_lock_sig, mapped_source = pkg_to_lock[package_signature]
            if load_json_document(PACKAGE_LOCK_SUBDIR, mapped_lock_sig) is not None:
                # Reuse existing lock for identical package signature
                reused += 1
                update_lock_manifest_entry(manifest, mapped_lock_sig, repo_key, package_signature, mapped_source)
                lock_repo_index[repo_key] = build_lock_repo_metadata(
                    item, package_signature, mapped_lock_sig, mapped_source
                )
                continue

        lock_content: Optional[Dict[str, Any]] = None
        try:
            lock_content, _ = fetch_package_lock_from_repo(item)
        except requests.HTTPError as exc:
            status_code = exc.response.status_code if exc.response else "error"
            reason = f"HTTP {status_code}"
            failures[reason] = failures.get(reason, 0) + 1
            click.echo(
                f"[Error] al consultar package-lock.json de {item['repository']['name']}: {reason}"
            )
        except requests.RequestException as exc:
            reason = exc.__class__.__name__
            failures[reason] = failures.get(reason, 0) + 1
            click.echo(
                f"[Error] al consultar package-lock.json de {item['repository']['name']}: {exc}"
            )

        if lock_content is None:
            package_content = load_json_document(PACKAGE_JSON_SUBDIR, package_signature)
            if package_content is None:
                failures["missing_package_json"] = failures.get("missing_package_json", 0) + 1
                click.echo(
                    f"[Error] package.json no encontrado en cache para firma {package_signature[:8]}"
                )
                continue
            lock_content = generate_lock_with_npm(package_content)
            source = "generated"
            if lock_content is None:
                failures["npm_failed"] = failures.get("npm_failed", 0) + 1
                continue
        else:
            source = "repository"

        if source == "generated":
            generated += 1
        else:
            downloaded += 1

        lock_signature = signature_for_json(lock_content)
        save_json_document(PACKAGE_LOCK_SUBDIR, lock_signature, lock_content)
        update_lock_manifest_entry(manifest, lock_signature, repo_key, package_signature, source)
        lock_repo_index[repo_key] = build_lock_repo_metadata(
            item, package_signature, lock_signature, source
        )
        # Update in-memory mapping so subsequent identical package signatures in this run reuse
        pkg_to_lock.setdefault(package_signature, (lock_signature, source))

    save_index(PACKAGE_LOCK_MANIFEST_FILE, manifest)
    save_index(PACKAGE_LOCK_REPO_INDEX_FILE, lock_repo_index)

    if not lock_repo_index:
        raise click.ClickException("No se cacheo ningun package-lock. Revisa paso 02 o la conectividad a Azure DevOps.")

    failure_summary = ", ".join(
        f"{reason}: {count}" for reason, count in sorted(failures.items())
    )
    if failure_summary:
        failure_summary = f" Errores -> {failure_summary}."

    click.echo(
        "package-lock cache actualizada. "
        f"Descargados: {downloaded}. Generados: {generated}. Reutilizados: {reused}. "
        f"Total firmas: {len(manifest)}." + failure_summary
    )


@click.command(help="Step 03: Get package-lock.json desde repos o generados")
@click.option("--force", is_flag=True, help="Forzar regeneración de package-lock.json")
def run(force: bool = False) -> None:
    get_package_lock(force=force)

if __name__ == '__main__':
    run()
