import os
import json
import click
from typing import Any, Dict, List, Optional
import requests
from requests.auth import HTTPBasicAuth

# Configuración de Azure DevOps (puede sobreescribirse con variables de entorno)
ORG = os.getenv('AZURE_ORG', 'flujodetrabajot')
PAT = os.getenv('AZURE_PAT') or os.getenv('SYSTEM_ACCESSTOKEN', '') or ''
if not PAT:
    click.echo('[Warn] Token de Azure DevOps no configurado; se intentara sin autenticacion.', err=True)

# Autenticación
auth = HTTPBasicAuth('', PAT)

# Cache de repositorios
# Cache de repositorios
try:
    from .cache_utils import CACHE_ROOT as _CACHE_ROOT  # package execution
except ImportError:
    from cache_utils import CACHE_ROOT as _CACHE_ROOT   # module execution
CACHE_DIR = str(_CACHE_ROOT)
CACHE_FILE = str(_CACHE_ROOT / 'repos_cache.json')

_DEFAULT_PAGE_SIZE = 500


def _resolve_page_size(value: Optional[str]) -> int:
    try:
        resolved = int(value) if value is not None else _DEFAULT_PAGE_SIZE
        if resolved > 0:
            return resolved
    except (TypeError, ValueError):
        pass
    return _DEFAULT_PAGE_SIZE


CODESEARCH_PAGE_SIZE = _resolve_page_size(os.getenv('AZURE_CODESEARCH_PAGE_SIZE'))



def ensure_cache_dir() -> None:
    """Crea el directorio de cache si no existe."""
    click.echo(f"[Info]: Cache directory path: {CACHE_DIR}")
    if not os.path.exists(CACHE_DIR):
        click.echo(f"[Info]: Creando cache directory en {CACHE_DIR}")
        os.makedirs(CACHE_DIR, exist_ok=True)



def load_repos_cache() -> Optional[List[Dict[str, Any]]]:
    """Carga lista de repositorios de cache si existe."""
    click.echo(f"[Info]: Cache file path: {CACHE_FILE}")
    if os.path.exists(CACHE_FILE):
        click.echo(f"[Info]: Cargando cache de repositorios desde {CACHE_FILE}")
        with open(CACHE_FILE, 'r', encoding='utf-8') as f:
            try:
                return json.load(f)
            except json.JSONDecodeError:
                return None
    return None



def save_repos_cache(repos: List[Dict[str, Any]]) -> None:
    """Guarda lista de repositorios en cache."""
    ensure_cache_dir()
    with open(CACHE_FILE, 'w', encoding='utf-8') as f:
        json.dump(repos, f, indent=2)



def fetch_repositories(skip: int = 0, top: int = CODESEARCH_PAGE_SIZE) -> List[Dict[str, Any]]:
    """
    Consulta Azure DevOps para repositorios con package.json.

    Args:
        skip: cuantos registros omitir
        top: cuantos registros recuperar
    Returns:
        Lista de objetos de resultado
    """
    url = f"https://almsearch.dev.azure.com/{ORG}/_apis/search/codesearchresults?api-version=7.1"
    click.echo(f"[Info]: Consultando Azure DevOps: url={url}, skip={skip}, top={top}")
    payload = {"searchText": "filename:package.json",
               "$skip": skip, "$top": top}
    headers = {"Content-Type": "application/json"}
    try:
        resp = requests.post(url, auth=auth, headers=headers, json=payload, timeout=10)
        resp.raise_for_status()
    except requests.RequestException as e:
        click.echo(f"[Error]: consultando Azure DevOps: {e}")
        return []
    try:
        data = resp.json()
    except ValueError as e:
        click.echo(f"[Error]: parseando respuesta JSON: {e}")
        return []
    return data.get('results', [])



def fetch_all_repositories(page_size: Optional[int] = None) -> List[Dict[str, Any]]:
    """Obtiene todas las coincidencias paginando hasta agotar resultados."""
    effective_page_size = page_size if page_size and page_size > 0 else CODESEARCH_PAGE_SIZE
    aggregated: List[Dict[str, Any]] = []
    skip = 0

    while True:
        batch = fetch_repositories(skip=skip, top=effective_page_size)
        if not batch:
            break
        aggregated.extend(batch)
        batch_size = len(batch)
        skip += batch_size
        if batch_size < effective_page_size:
            break

    return aggregated



def get_repositories(force: bool = False) -> Optional[List[Dict[str, Any]]]:
    """
    Obtiene lista de repositorios, usando cache a menos que force=True.
    """
    if not force:
        cached = load_repos_cache()
        if cached is not None:
            print(f"Usando cache de repositorios ({len(cached)} items)")
            return cached
    repos = fetch_all_repositories()
    click.echo(f"[Info]: Repositorios obtenidos: {len(repos)}")
    save_repos_cache(repos)
    click.echo("[Info]: Repos cargados utilizando cache")
    return repos


@click.command(help='Step 01: Get Repositories')
@click.option('--force', is_flag=True, help='Forzar refresco del cache')
def run(force: bool = False):
    click.echo(f"[Info]: run step_01_get_repositories with force={force}")
    """Invoca la obtención de repositorios, opcionalmente forzando cache."""
    try:
        get_repositories(force=force)
    except Exception as e:
        click.echo(f"[Error]: obteniendo repositorios: {e}")

if __name__ == '__main__':
    run()