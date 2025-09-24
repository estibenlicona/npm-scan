from typing import Any, Dict

import click
import requests

try:
    from .step_01_get_repositories import ORG, auth, load_repos_cache
    from .cache_utils import (
        build_repo_key,
        load_index,
        save_index,
        save_json_document,
        signature_for_json,
    )
except ImportError:
    from step_01_get_repositories import ORG, auth, load_repos_cache
    from cache_utils import (
        build_repo_key,
        load_index,
        save_index,
        save_json_document,
        signature_for_json,
    )

PACKAGE_JSON_SUBDIR = "package_json"
PACKAGES_MANIFEST_FILE = "packages_cache.json"
PACKAGES_REPO_INDEX_FILE = "package_json_repo_index.json"


def load_packages_manifest() -> Dict[str, Dict[str, Any]]:
    """Load the package.json manifest, migrating legacy payloads if needed."""
    manifest_raw = load_index(PACKAGES_MANIFEST_FILE)
    if not isinstance(manifest_raw, dict):
        manifest_raw = {}
    manifest: Dict[str, Dict[str, Any]] = {}
    migrated = False
    for signature, payload in manifest_raw.items():
        if isinstance(payload, dict) and "path" in payload and "repos" in payload:
            manifest[signature] = {
                "path": payload.get("path", f"{PACKAGE_JSON_SUBDIR}/{signature}.json"),
                "repos": payload.get("repos", []),
            }
            continue
        if isinstance(payload, dict):
            save_json_document(PACKAGE_JSON_SUBDIR, signature, payload)
            manifest[signature] = {
                "path": f"{PACKAGE_JSON_SUBDIR}/{signature}.json",
                "repos": [],
            }
            migrated = True
    if migrated:
        save_index(PACKAGES_MANIFEST_FILE, manifest)
    return manifest



def load_repo_index() -> Dict[str, Dict[str, Any]]:
    repo_index = load_index(PACKAGES_REPO_INDEX_FILE)
    if isinstance(repo_index, dict):
        return repo_index
    return {}



def fetch_package_json(item: Dict[str, Any]) -> Any:
    project = item["project"]["name"]
    repo_id = item["repository"]["id"]
    path = item["path"]
    versions = item.get("versions") or []
    branch = versions[0].get("branchName", "") if versions else ""
    url = f"https://dev.azure.com/{ORG}/{project}/_apis/git/repositories/{repo_id}/items"
    params: Dict[str, Any] = {
        "path": path,
        "includeContent": True,
        "versionDescriptor.version": branch,
        "api-version": "7.1",
    }
    resp = requests.get(url, auth=auth, params=params, timeout=10)
    resp.raise_for_status()
    return resp.json()



def update_manifest_entry(
    manifest: Dict[str, Dict[str, Any]], signature: str, repo_key: str
) -> None:
    entry = manifest.get(
        signature,
        {
            "path": f"{PACKAGE_JSON_SUBDIR}/{signature}.json",
            "repos": [],
        },
    )
    repos = set(entry.get("repos") or [])
    repos.add(repo_key)
    entry["repos"] = sorted(repos)
    entry["path"] = f"{PACKAGE_JSON_SUBDIR}/{signature}.json"
    manifest[signature] = entry



def build_repo_metadata(item: Dict[str, Any], signature: str) -> Dict[str, Any]:
    versions = item.get("versions") or []
    branch = versions[0].get("branchName", "") if versions else ""
    return {
        "signature": signature,
        "repositoryId": item["repository"]["id"],
        "repositoryName": item["repository"].get("name"),
        "project": item["project"].get("name"),
        "path": item.get("path"),
        "branch": branch,
    }



def get_packagesjson(force: bool = False) -> None:
    repos = load_repos_cache()
    try:
        repo_count = len(repos) if isinstance(repos, list) else 0
        click.echo(f"[Info]: repos_count={repo_count}")
    except Exception:
        pass
    if not repos:
        raise click.ClickException(
            "No se encontro cache de repositorios. Ejecuta step_01 primero o revisa las credenciales."
        )

    manifest = load_packages_manifest()
    repo_index = load_repo_index()

    new_downloads = 0
    reused = 0
    failures: Dict[str, int] = {}
    click.echo(f"Procesando {len(repos)} entradas de package.json...")
    for item in repos:
        repo_key = build_repo_key(item)
        if not force and repo_key in repo_index:
            reused += 1
            continue
        try:
            package_data = fetch_package_json(item)
        except requests.HTTPError as exc:
            status = exc.response.status_code if exc.response else "error"
            reason = f"HTTP {status}"
            failures[reason] = failures.get(reason, 0) + 1
            click.echo(
                f"[Error] al descargar package.json de {item['repository']['name']}: {reason}"
            )
            continue
        except requests.RequestException as exc:
            reason = exc.__class__.__name__
            failures[reason] = failures.get(reason, 0) + 1
            click.echo(
                f"[Error] al descargar package.json de {item['repository']['name']}: {exc}"
            )
            continue

        signature = signature_for_json(package_data)
        save_json_document(PACKAGE_JSON_SUBDIR, signature, package_data)
        update_manifest_entry(manifest, signature, repo_key)
        repo_index[repo_key] = build_repo_metadata(item, signature)
        new_downloads += 1

    if not repo_index:
        raise click.ClickException(
            "No se generaron entradas en el indice de package.json. Revisa step_01 o la conectividad a Azure DevOps."
        )

    save_index(PACKAGES_MANIFEST_FILE, manifest)
    save_index(PACKAGES_REPO_INDEX_FILE, repo_index)

    failure_summary = ", ".join(
        f"{reason}: {count}" for reason, count in sorted(failures.items())
    )
    if failure_summary:
        failure_summary = f" Errores -> {failure_summary}."

    click.echo(
        "package.json cache actualizada. "
        f"Nuevos: {new_downloads}. Reutilizados: {reused}. Total firmas: {len(manifest)}." + failure_summary
    )


@click.command(help="Step 02: Get package.json and cache by signature")
@click.option("--force", is_flag=True, help="Forzar refresco de cache de packages")
def run(force: bool = False) -> None:
    get_packagesjson(force=force)

if __name__ == '__main__':
    run()

