import os
import json
import click
from typing import Any, Dict, List, Optional
import requests
from requests.auth import HTTPBasicAuth

# Configuración de Azure DevOps (puede sobreescribirse con variables de entorno)
ORG = os.getenv('AZURE_ORG', 'estibenlicona')
PAT = os.getenv(
    'AZURE_PAT', 'Ft4wuvaHItmDNIO03qImSjbggPXcz4uT0jBrpBVUoiByXAVVboYiJQQJ99BIACAAAAAAAAAAAAASAZDO3IKn')

# Autenticación
auth = HTTPBasicAuth('', PAT)

# Cache de repositorios
CACHE_DIR = os.path.join(os.getcwd(), '.npm_scan_cache')
CACHE_FILE = os.path.join(CACHE_DIR, 'repos_cache.json')


def ensure_cache_dir() -> None:
    """Crea el directorio de cache si no existe."""
    if not os.path.exists(CACHE_DIR):
        os.makedirs(CACHE_DIR, exist_ok=True)


def load_repos_cache() -> Optional[List[Dict[str, Any]]]:
    """Carga lista de repositorios de cache si existe."""
    if os.path.exists(CACHE_FILE):
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


def fetch_repositories(skip: int = 0, top: int = 500) -> List[Dict[str, Any]]:
    """
    Consulta Azure DevOps para repositorios con package.json.

    Args:
        skip: cuantos registros omitir
        top: cuantos registros recuperar
    Returns:
        Lista de objetos de resultado
    """
    url = f"https://almsearch.dev.azure.com/{ORG}/_apis/search/codesearchresults?api-version=7.1"
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


def get_repositories(force: bool = False):
    """
    Obtiene lista de repositorios, usando cache a menos que force=True.
    """
    if not force:
        cached = load_repos_cache()
        if cached is not None:
            print(f"Usando cache de repositorios ({len(cached)} items)")
            return cached
    repos = fetch_repositories()
    save_repos_cache(repos)
    click.echo("Repos cargados utilizando cache")


@click.command(help='Step 01: Get Repositories')
@click.option('--force', is_flag=True, help='Forzar refresco del cache')
def run(force: bool = False):
    """Invoca la obtención de repositorios, opcionalmente forzando cache."""
    get_repositories(force=force)
