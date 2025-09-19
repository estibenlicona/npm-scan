import requests
from requests.auth import HTTPBasicAuth
import json
from typing import Any
import semver  # pip install semver

# Configuración
ORG = "estibenlicona"
PROJECT = "Test"  # o None si quieres buscar en toda la org
PAT = ""  # tu Personal Access Token
PACKAGE_NAME = "tslib"
TARGET_VERSION = "2.3.0"

auth = HTTPBasicAuth("", PAT)

# 1. Buscar el paquete con Code Search
search_url = f"https://almsearch.dev.azure.com/{ORG}/_apis/search/codesearchresults?api-version=7.1-preview.1"

body: dict[str, Any] = {
    "searchText": f"\"{PACKAGE_NAME}\" filename:package.json",
    "$skip": 0,
    "$top": 200
}
if PROJECT:
    body["filters"] = {"Project": [PROJECT]}

resp = requests.post(search_url, auth=auth, headers={"Content-Type": "application/json"}, json=body)
resp.raise_for_status()
results = resp.json()["results"]

print(f"Encontrados {len(results)} resultados para {PACKAGE_NAME}")

# 2. Revisar cada repo y descargar package.json
for r in results:
    repo_id = r["repository"]["id"]
    repo_name = r["repository"]["name"]
    project = r["project"]["name"]
    path = r["path"]
    branch = r["versions"][0]["branchName"]

    items_url = f"https://dev.azure.com/{ORG}/{project}/_apis/git/repositories/{repo_id}/items"
    params: dict[str, Any] = {
        "path": path,
        "versionDescriptor.version": branch,
        "includeContent": "true",
        "api-version": "7.1"
    }
    file_resp = requests.get(items_url, auth=auth, params=params)
    file_resp.raise_for_status()
    content = file_resp.json().get("content", "")

    try:
        pkg_json = json.loads(content)
    except json.JSONDecodeError:
        print(f"[WARN] No se pudo parsear package.json en {project}/{repo_name}")
        continue

    deps = pkg_json.get("dependencies", {})
    dev_deps = pkg_json.get("devDependencies", {})
    all_deps = {**deps, **dev_deps}

    if PACKAGE_NAME in all_deps:
        declared_range = all_deps[PACKAGE_NAME]
        try:
            # Parse the target version to a Version object
            target_ver = semver.Version.parse(TARGET_VERSION)
            # Use match method to check if the version satisfies the range
            # Note: semver.match expects operator and version, but npm ranges are different
            # For basic version matching, we'll do a simple comparison
            if declared_range.startswith('^'):
                # Caret range: ^1.2.3 means >=1.2.3 <2.0.0
                base_version = declared_range[1:]
                base_ver = semver.Version.parse(base_version)
                satisfies = (target_ver >= base_ver and 
                            target_ver.major == base_ver.major)
            elif declared_range.startswith('~'):
                # Tilde range: ~1.2.3 means >=1.2.3 <1.3.0
                base_version = declared_range[1:]
                base_ver = semver.Version.parse(base_version)
                satisfies = (target_ver >= base_ver and 
                            target_ver.major == base_ver.major and
                            target_ver.minor == base_ver.minor)
            elif any(op in declared_range for op in ['>=', '<=', '>', '<', '==']):
                # Direct comparison operators
                satisfies = target_ver.match(declared_range)
            else:
                # Exact version match
                satisfies = str(target_ver) == declared_range
        except Exception as e:
            satisfies = False
        print(f"{project}/{repo_name} → {PACKAGE_NAME} {declared_range} → "
              f"{'✔ cubre ' + TARGET_VERSION if satisfies else '✘ no cubre ' + TARGET_VERSION}")
