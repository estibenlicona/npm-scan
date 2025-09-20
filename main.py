import requests
from requests.auth import HTTPBasicAuth
from typing import Any, Dict, List, TypedDict, Optional
import semver  # pip install semver
import tempfile
import os
import subprocess
import json
import shutil
from datetime import datetime
import hashlib
import pickle

# Tipos para mejorar el type checking
class RepoData(TypedDict):
    project: str
    repo_name: str
    dependencies: Dict[str, str]
    lock_dependencies: Dict[str, List[str]]  # Dependencias desde package-lock.json (múltiples versiones)
    has_lock_file: bool

class VulnerabilityInfo(TypedDict):
    package_name: str
    target_version: str  # Versión vulnerable que estamos buscando
    version_range: str   # Rango declarado (ej: "^2.0.0") 
    actual_version: Optional[str]  # Versión exacta instalada (si existe)
    is_vulnerable: bool  # Si el rango incluye la versión vulnerable
    is_secure: bool      # Si está seguro (no incluye versión vulnerable)
    dependency_type: str # "DIRECTO", "TRANSITIVA", "INSTALADA"

class RepositoryResult(TypedDict):
    project: str
    repository_name: str
    path: str
    has_package_lock: bool
    direct_dependencies: List[VulnerabilityInfo]    # Dependencias directas
    transitive_dependencies: List[VulnerabilityInfo] # Dependencias transitivas

class ScanResults(TypedDict):
    scan_date: str
    packages_analyzed: List[Dict[str, str]]  # [{"name": "react", "target_version": "18.0.0"}]
    npm_available: bool
    total_repositories: int
    repositories: List[RepositoryResult]
    summary: Dict[str, int]  # Contadores de vulnerable/secure/etc

# Configuración
ORG = "flujodetrabajot"
PROJECT = "Tuya - Tecnologia"  # o None si quieres buscar en toda la org
PAT = "BCY1DgMHEAkihceor2h8vRfbiNetPB2aBtziXjanq0RyTM3aF3WIJQQJ99BDACAAAAA7a3kzAAASAZDO4dwm"  # tu Personal Access Token

# Configuración de caché
CACHE_DIR = os.path.join(os.getcwd(), ".npm_scan_cache")
CACHE_FILE = os.path.join(CACHE_DIR, "package_lock_cache.pkl")

# Configuración de autenticación
auth = HTTPBasicAuth("", PAT)

def generate_package_json_signature(package_json_content: Dict[str, Any]) -> str:
    """
    Genera una firma única del package.json para usar como clave de caché.
    
    Args:
        package_json_content: Contenido del package.json
        
    Returns:
        str: Firma SHA256 del contenido relevante del package.json
    """
    # Solo incluir las secciones relevantes para package-lock.json
    relevant_data = {
        "dependencies": package_json_content.get("dependencies", {}),
        "devDependencies": package_json_content.get("devDependencies", {}),
        "peerDependencies": package_json_content.get("peerDependencies", {}),
        "optionalDependencies": package_json_content.get("optionalDependencies", {}),
        "name": package_json_content.get("name", ""),
        "version": package_json_content.get("version", "")
    }
    
    # Convertir a JSON string determinista (ordenado)
    json_string = json.dumps(relevant_data, sort_keys=True)
    
    # Generar hash SHA256
    return hashlib.sha256(json_string.encode('utf-8')).hexdigest()

def ensure_cache_directory():
    """
    Asegura que el directorio de caché existe.
    """
    if not os.path.exists(CACHE_DIR):
        os.makedirs(CACHE_DIR)
        print(f"  📁 Directorio de caché creado: {CACHE_DIR}")

def load_cache() -> Dict[str, Dict[str, List[str]]]:
    """
    Carga la caché desde el archivo pickle.
    
    Returns:
        Dict: Caché de package-lock.json {signature: {package_name: [versions]}}
    """
    try:
        if os.path.exists(CACHE_FILE):
            with open(CACHE_FILE, 'rb') as f:
                cache = pickle.load(f)
                if cache:
                    print(f"    📦 Caché cargada con {len(cache)} entradas desde {CACHE_FILE}")
                else:
                    print(f"    📭 Caché vacía encontrada en {CACHE_FILE}")
                return cache
        else:
            print(f"    📭 No existe archivo de caché: {CACHE_FILE}")
    except Exception as e:
        print(f"    ⚠️  Error cargando caché desde {CACHE_FILE}: {e}")
    
    return {}

def save_cache(cache: Dict[str, Dict[str, List[str]]]):
    """
    Guarda la caché en el archivo pickle.
    
    Args:
        cache: Caché a guardar
    """
    try:
        ensure_cache_directory()
        with open(CACHE_FILE, 'wb') as f:
            pickle.dump(cache, f)
            print(f"    💾 Caché guardada con {len(cache)} entradas en {CACHE_FILE}")
    except Exception as e:
        print(f"    ⚠️  Error guardando caché en {CACHE_FILE}: {e}")

def get_cached_lock_deps(package_json_signature: str) -> Optional[Dict[str, List[str]]]:
    """
    Obtiene las dependencias del package-lock.json desde la caché.
    
    Args:
        package_json_signature: Firma del package.json
        
    Returns:
        Dict: Dependencias filtradas o None si no está en caché
    """
    cache = load_cache()
    if package_json_signature in cache:
        cached_data = cache[package_json_signature]
        total_cached = sum(len(versions) for versions in cached_data.values())
        print(f"    ✅ Encontrado en caché (firma: {package_json_signature[:12]}...) - {total_cached} dependencias")
        return cached_data
    else:
        print(f"    🔍 No encontrado en caché (firma: {package_json_signature[:12]}...)")
        return None

def cache_lock_deps(package_json_signature: str, lock_deps: Dict[str, List[str]]):
    """
    Guarda las dependencias del package-lock.json en la caché.
    
    Args:
        package_json_signature: Firma del package.json
        lock_deps: Dependencias filtradas a guardar
    """
    cache = load_cache()
    cache[package_json_signature] = lock_deps
    total_deps = sum(len(versions) for versions in lock_deps.values())
    save_cache(cache)
    print(f"    💾 Guardado en caché (firma: {package_json_signature[:12]}...) - {total_deps} dependencias")

def check_npm_available() -> bool:
    """
    Verifica si npm está disponible en el sistema.
    
    Returns:
        bool: True si npm está disponible, False en caso contrario
    """
    try:
        result = subprocess.run(["npm", "--version"], capture_output=True, text=True, timeout=10)
        return result.returncode == 0
    except Exception:
        return False

def load_packages_from_file(filename: str = "packages.txt") -> List[Dict[str, str]]:
    """
    Carga la lista de paquetes a escanear desde un archivo de texto.
    
    Args:
        filename: Nombre del archivo que contiene los paquetes
    
    Returns:
        List[Dict[str, str]]: Lista de paquetes en formato [{"name": "lodash", "target_version": "4.17.20"}]
    
    Formatos soportados del archivo:
        # Comentarios empiezan con #
        
        # Formato clásico con ==
        lodash==4.17.20
        react==16.13.0
        
        # Formato npm simple con @
        lodash@4.17.20
        react@16.13.0
        
        # Formato npm con scope
        @ctrl/golang-template@1.4.2
        @angular/core@15.2.0
    """
    packages: List[Dict[str, Any]] = []
    
    if not os.path.exists(filename):
        print(f"⚠️  Archivo {filename} no encontrado. Usando configuración por defecto.")
        return [
            {"name": "lodash", "target_version": "4.17.20"}
        ]
    
    try:
        with open(filename, 'r', encoding='utf-8') as f:
            for line_num, line in enumerate(f, 1):
                line = line.strip()
                
                # Saltar líneas vacías y comentarios
                if not line or line.startswith('#'):
                    continue
                
                # Parsear diferentes formatos
                name = ""
                version = ""
                
                if '==' in line:
                    # Formato: lodash==4.17.20
                    try:
                        name, version = line.split('==', 1)
                        name = name.strip()
                        version = version.strip()
                    except Exception as e:
                        print(f"⚠️  Error parseando línea {line_num} (formato ==): {line} - {e}")
                        continue
                        
                elif line.startswith('@') and '@' in line[1:]:
                    # Formato npm con scope: @ctrl/golang-template@1.4.2
                    try:
                        # Encontrar el último @ que separa el nombre de la versión
                        last_at = line.rfind('@')
                        if last_at > 0:  # Debe haber al menos un @ antes del último
                            name = line[:last_at].strip()
                            version = line[last_at + 1:].strip()
                        else:
                            print(f"⚠️  Línea {line_num} formato scope inválido: {line}")
                            continue
                    except Exception as e:
                        print(f"⚠️  Error parseando línea {line_num} (formato @scope): {line} - {e}")
                        continue
                        
                elif '@' in line and not line.startswith('@'):
                    # Formato npm simple: lodash@4.17.20
                    try:
                        parts = line.rsplit('@', 1)  # Dividir desde la derecha para evitar problemas con scopes
                        if len(parts) == 2:
                            name = parts[0].strip()
                            version = parts[1].strip()
                        else:
                            print(f"⚠️  Línea {line_num} formato @ inválido: {line}")
                            continue
                    except Exception as e:
                        print(f"⚠️  Error parseando línea {line_num} (formato @): {line} - {e}")
                        continue
                else:
                    print(f"⚠️  Línea {line_num} no tiene formato reconocido (== o @): {line}")
                    continue
                
                # Validar y agregar el paquete
                if name and version:
                    packages.append({
                        "name": name,
                        "target_version": version
                    })
                    print(f"  ✓ {name} @ {version}")
                else:
                    print(f"⚠️  Línea {line_num} inválida (nombre o versión vacía): {line}")
    
    except Exception as e:
        print(f"❌ Error leyendo archivo {filename}: {e}")
        print("📦 Usando configuración por defecto...")
        return [
            {"name": "lodash", "target_version": "4.17.20"}
        ]
    
    if not packages:
        print(f"⚠️  No se encontraron paquetes válidos en {filename}. Usando configuración por defecto.")
        return [
            {"name": "lodash", "target_version": "4.17.20"}
        ]
    
    print(f"✅ Cargados {len(packages)} paquetes desde {filename}")
    return packages

def check_version_satisfies(target_version: str, declared_range: str) -> bool:
    """
    Verifica si una versión objetivo satisface un rango de versiones npm.
    
    Args:
        target_version: La versión que queremos verificar (ej: "2.3.0")
        declared_range: El rango declarado en package.json (ej: "^2.0.0")
    
    Returns:
        bool: True si la versión satisface el rango, False en caso contrario
    """
    try:
        target_ver = semver.Version.parse(target_version)
        
        if declared_range.startswith('^'):
            # Caret range: ^1.2.3 means >=1.2.3 <2.0.0
            base_version = declared_range[1:]
            base_ver = semver.Version.parse(base_version)
            return (target_ver >= base_ver and target_ver.major == base_ver.major)
        elif declared_range.startswith('~'):
            # Tilde range: ~1.2.3 means >=1.2.3 <1.3.0
            base_version = declared_range[1:]
            base_ver = semver.Version.parse(base_version)
            return (target_ver >= base_ver and 
                   target_ver.major == base_ver.major and
                   target_ver.minor == base_ver.minor)
        elif any(op in declared_range for op in ['>=', '<=', '>', '<', '==']):
            # Direct comparison operators
            return target_ver.match(declared_range)
        else:
            # Exact version match
            return str(target_ver) == declared_range
    except Exception:
        return False

def is_version_vulnerable(vulnerable_version: str, declared_range: str) -> bool:
    """
    Verifica si un rango de versiones declarado incluye/cubre una versión vulnerable específica.
    
    Args:
        vulnerable_version: La versión vulnerable que queremos detectar (ej: "2.1.4")
        declared_range: El rango declarado en package.json (ej: "^2.0.0")
    
    Returns:
        bool: True si el rango incluye la versión vulnerable (PELIGROSO), False si está seguro
    """
    return check_version_satisfies(vulnerable_version, declared_range)

def extract_filtered_dependencies_from_lock(lock_content: Dict[str, Any], target_packages: List[str]) -> Dict[str, List[str]]:
    """
    Extrae solo las dependencias relevantes desde package-lock.json.
    Solo incluye paquetes que están en la lista de paquetes objetivo.
    IMPORTANTE: Recolecta TODAS las versiones encontradas de cada paquete, incluyendo 
    las que aparecen como dependencias directas, transitivas, y en todas las ubicaciones.
    
    Args:
        lock_content: Contenido del package-lock.json parseado
        target_packages: Lista de nombres de paquetes que estamos buscando
    
    Returns:
        Dict: Diccionario con dependencias filtradas {package_name: [version1, version2, ...]}
    """
    target_set = set(target_packages)  # Para búsqueda más eficiente
    filtered_deps: Dict[str, List[str]] = {}
    
    def add_version_if_target(package_name: str, version: str):
        """Helper para agregar una versión si el paquete es uno de los objetivos"""
        if package_name in target_set and version and version != "unknown":
            if package_name not in filtered_deps:
                filtered_deps[package_name] = []
            
            # Agregar versión solo si no está ya presente
            if version not in filtered_deps[package_name]:
                filtered_deps[package_name].append(version)
                print(f"    🔍 Encontrado {package_name}@{version}")
    
    # Extraer de lockfileVersion 2 y 3 (formato más reciente)
    if "packages" in lock_content:
        packages = lock_content["packages"]
        print(f"  📄 Analizando {len(packages)} entradas del package-lock.json...")
        
        for package_path, package_info in packages.items():
            if package_path == "":  # Skip root package
                continue
            
            # 1. Verificar si el path del paquete contiene uno de nuestros objetivos
            for target_pkg in target_packages:
                if target_pkg in package_path:
                    version = package_info.get("version")
                    if version:
                        add_version_if_target(target_pkg, version)
            
            # 2. Buscar en todas las secciones de dependencias de cada paquete
            for dep_section in ["dependencies", "peerDependencies", "devDependencies", "optionalDependencies"]:
                if dep_section in package_info:
                    deps = package_info[dep_section]
                    for dep_name, dep_range in deps.items():
                        # Si esta dependencia es una de las que buscamos
                        if dep_name in target_set:
                            # Buscar la versión instalada de esta dependencia
                            installed_version = find_installed_version(packages, dep_name, package_path)
                            if installed_version:
                                add_version_if_target(dep_name, installed_version)
    
    # Fallback para lockfileVersion 1 (formato más antiguo)
    elif "dependencies" in lock_content:
        dependencies = lock_content["dependencies"]
        filtered_deps = extract_dependencies_recursive_filtered(dependencies, target_set)
    
    return filtered_deps

def find_installed_version(packages: Dict[str, Any], dep_name: str, parent_path: str) -> Optional[str]:
    """
    Encuentra la versión instalada de una dependencia específica.
    Busca en múltiples ubicaciones posibles siguiendo la resolución de Node.js.
    
    Args:
        packages: Diccionario de paquetes del lock file
        dep_name: Nombre de la dependencia a buscar
        parent_path: Ruta del paquete padre
        
    Returns:
        str: Versión encontrada o None
    """
    # Buscar en diferentes ubicaciones según el algoritmo de resolución de Node.js
    search_paths = []
    
    # 1. Dentro del node_modules del paquete padre
    if parent_path and parent_path != "":
        search_paths.append(f"{parent_path}/node_modules/{dep_name}")
    
    # 2. En node_modules raíz
    search_paths.append(f"node_modules/{dep_name}")
    
    # 3. Buscar en cualquier path que contenga el nombre del paquete
    for path, info in packages.items():
        if path.endswith(f"/{dep_name}") or path == f"node_modules/{dep_name}":
            version = info.get("version")
            if version:
                return version
    
    return None

def extract_dependencies_recursive_filtered(dependencies: Dict[str, Any], target_set: set[str]) -> Dict[str, List[str]]:
    """
    Extrae dependencias de forma recursiva para lockfileVersion 1, filtrando solo las relevantes.
    IMPORTANTE: Recolecta TODAS las versiones encontradas de cada paquete.
    
    Args:
        dependencies: Diccionario de dependencias
        target_set: Set de nombres de paquetes que estamos buscando
    
    Returns:
        Dict: Dependencias filtradas {package_name: [version1, version2, ...]}
    """
    filtered_deps: Dict[str, List[str]] = {}
    
    for package_name, package_info in dependencies.items():
        # Solo procesar si es uno de los paquetes que buscamos
        if package_name in target_set:
            version = package_info.get("version", "unknown")
            
            # Inicializar lista si no existe
            if package_name not in filtered_deps:
                filtered_deps[package_name] = []
            
            # Agregar versión solo si no está ya presente
            if version not in filtered_deps[package_name]:
                filtered_deps[package_name].append(version)
        
        # Procesar subdependencias recursivamente (siempre, porque pueden contener paquetes objetivo)
        if "dependencies" in package_info:
            sub_deps = extract_dependencies_recursive_filtered(package_info["dependencies"], target_set)
            # Combinar las listas de versiones
            for pkg_name, versions in sub_deps.items():
                if pkg_name not in filtered_deps:
                    filtered_deps[pkg_name] = []
                
                # Agregar versiones que no estén ya presentes
                for version in versions:
                    if version not in filtered_deps[pkg_name]:
                        filtered_deps[pkg_name].append(version)
    
    return filtered_deps

def download_package_json(org: str, project: str, repo_id: str, branch: str) -> Dict[str, Any]:
    """
    Descarga el contenido completo del package.json desde Azure DevOps.
    
    Returns:
        Dict: Contenido del package.json parseado
    """
    items_url = f"https://dev.azure.com/{org}/{project}/_apis/git/repositories/{repo_id}/items"
    params: Dict[str, Any] = {
        "path": "/package.json",
        "versionDescriptor.version": branch,
        "includeContent": "true",
        "api-version": "7.1"
    }
    
    file_resp = requests.get(items_url, auth=auth, params=params)
    file_resp.raise_for_status()
    return file_resp.json()

def generate_package_lock(package_json_content: Dict[str, Any], target_packages: List[str]) -> Dict[str, List[str]]:
    """
    Genera un package-lock.json usando npm install --package-lock-only.
    Usa caché basada en la firma del package.json para evitar regeneraciones innecesarias.
    
    Args:
        package_json_content: Contenido del package.json
        target_packages: Lista de paquetes que estamos buscando
        
    Returns:
        Dict: Dependencias filtradas extraídas del package-lock.json generado {package_name: [version1, version2, ...]}
    """
    # Generar firma del package.json
    signature = generate_package_json_signature(package_json_content)
    print(f"    🔐 Firma del package.json: {signature[:12]}...")
    
    # Verificar caché primero
    cached_deps = get_cached_lock_deps(signature)
    if cached_deps is not None:
        total_relevant = sum(len(versions) for versions in cached_deps.values())
        print(f"    🚀 CACHÉ UTILIZADA - Evitando npm install, {total_relevant} dependencias cargadas instantáneamente")
        return cached_deps
    
    # No está en caché, generar package-lock.json
    print(f"    🔧 No encontrado en caché, generando package-lock.json...")
    lock_deps: Dict[str, List[str]] = {}
    temp_dir = None
    
    try:
        # Crear directorio temporal
        temp_dir = tempfile.mkdtemp(prefix="npm_scan_")
        package_json_path = os.path.join(temp_dir, "package.json")
        package_lock_path = os.path.join(temp_dir, "package-lock.json")
        
        # Escribir package.json temporal
        with open(package_json_path, 'w', encoding='utf-8') as f:
            json.dump(package_json_content, f, indent=2)
        
        print(f"    🔧 Ejecutando npm install...")
        
        # Ejecutar npm install --package-lock-only
        result = subprocess.run([
            "npm", "install", "--package-lock-only", "--legacy-peer-deps", "--ignore-scripts", "--no-audit", "--no-fund"
        ], cwd=temp_dir, capture_output=True, text=True, timeout=120)
        
        if result.returncode == 0 and os.path.exists(package_lock_path):
            # Leer y parsear el package-lock.json generado
            with open(package_lock_path, 'r', encoding='utf-8') as f:
                lock_content = json.load(f)
            
            # Solo extraer dependencias de los paquetes que buscamos
            lock_deps = extract_filtered_dependencies_from_lock(lock_content, target_packages)
            total_relevant = sum(len(versions) for versions in lock_deps.values())
            print(f"    ✅ package-lock.json generado - {total_relevant} dependencias relevantes encontradas")
            
            # Guardar en caché
            cache_lock_deps(signature, lock_deps)
        else:
            print(f"    ❌ Error generando package-lock.json: {result.stderr}")
            
    except subprocess.TimeoutExpired:
        print(f"    ⏱️ Timeout generando package-lock.json")
    except Exception as e:
        print(f"    ❌ Error en generación: {e}")
    finally:
        # Limpiar directorio temporal
        if temp_dir and os.path.exists(temp_dir):
            shutil.rmtree(temp_dir, ignore_errors=True)
    
    return lock_deps

def get_lock_file_content(org: str, project: str, repo_id: str, branch: str, target_packages: List[str], package_json_content: Optional[Dict[str, Any]] = None) -> Dict[str, List[str]]:
    """
    Intenta descargar package-lock.json o generarlo si no existe.
    
    Args:
        target_packages: Lista de paquetes que estamos buscando
        package_json_content: Contenido del package.json (opcional, se descarga si no se proporciona)
    
    Returns:
        Dict: Dependencias filtradas extraídas del lock file {package_name: [version1, version2, ...]}
    """
    lock_deps: Dict[str, List[str]] = {}
    
    # Intentar con package-lock.json existente primero
    for lock_file in ["package-lock.json", "yarn.lock"]:
        try:
            items_url = f"https://dev.azure.com/{org}/{project}/_apis/git/repositories/{repo_id}/items"
            params: Dict[str, Any] = {
                "path": f"/{lock_file}",
                "versionDescriptor.version": branch,
                "includeContent": "true",
                "api-version": "7.1"
            }
            
            file_resp = requests.get(items_url, auth=auth, params=params)
            
            if file_resp.status_code == 200:
                if lock_file == "package-lock.json":
                    lock_json = file_resp.json()
                    lock_deps = extract_filtered_dependencies_from_lock(lock_json, target_packages)
                    if lock_deps:
                        total_relevant = sum(len(versions) for versions in lock_deps.values())
                        print(f"    ✅ Encontrado package-lock.json existente - {total_relevant} dependencias relevantes")
                        return lock_deps  # Encontrado package-lock.json existente
                # TODO: Implementar parser para yarn.lock si es necesario
                
        except Exception:
            continue  # Intentar con el siguiente archivo
    
    # Si no se encontró package-lock.json, intentar generarlo
    if not lock_deps and check_npm_available():
        try:
            if package_json_content is None:
                print(f"    📄 Descargando package.json para generar lock file...")
                package_json_content = download_package_json(org, project, repo_id, branch)
            
            # Verificar que hay dependencias para generar
            has_deps = (
                package_json_content.get("dependencies", {}) or 
                package_json_content.get("devDependencies", {})
            )
            
            if has_deps:
                lock_deps = generate_package_lock(package_json_content, target_packages)
            else:
                print(f"    ℹ️  No hay dependencias para generar package-lock.json")
                
        except Exception as e:
            print(f"    ❌ Error intentando generar package-lock.json: {e}")
    elif not lock_deps:
        print(f"    ⚠️  No se encontró package-lock.json y npm no está disponible para generarlo")
    
    return lock_deps

def search_repositories_with_package_json() -> List[Dict[str, Any]]:
    """
    Busca todos los repositorios que contengan package.json.
    
    Returns:
        List: Lista de resultados de búsqueda con repositorios que tienen package.json
    """
    search_url = f"https://almsearch.dev.azure.com/{ORG}/_apis/search/codesearchresults?api-version=7.1"
    
    body: Dict[str, Any] = {
        "searchText": "filename:package.json",
        "$skip": 0,
        "$top": 500  # Aumentamos el límite para obtener más repositorios
    }
    
    print("🔍 Buscando repositorios con package.json...")
    resp = requests.post(search_url, auth=auth, headers={"Content-Type": "application/json"}, json=body)
    resp.raise_for_status()
    return resp.json()["results"]

# 1. Verificar que npm está disponible
print("="*80)
print("ESCANEANDO PAQUETES NPM EN AZURE DEVOPS")
print("="*80)

npm_available = check_npm_available()
if npm_available:
    print("✅ npm detectado - Se pueden generar package-lock.json cuando sea necesario")
else:
    print("⚠️  npm no encontrado - Solo se analizarán package-lock.json existentes")

# Cargar lista de paquetes desde archivo externo
print("\n📋 Cargando lista de paquetes...")
PACKAGES_TO_CHECK = load_packages_from_file("packages.txt")

# Inicializar caché
print("📁 Inicializando sistema de caché...")
ensure_cache_directory()

# Inicializar estructura de resultados
scan_results: ScanResults = {
    "scan_date": datetime.now().isoformat(),
    "packages_analyzed": PACKAGES_TO_CHECK,
    "npm_available": npm_available,
    "total_repositories": 0,
    "repositories": [],
    "summary": {
        "total_vulnerable": 0,
        "total_secure": 0,
        "total_direct_dependencies": 0,
        "total_transitive_dependencies": 0
    }
}

all_repos_data: Dict[str, RepoData] = {}  # Cache para evitar descargar el mismo package.json múltiples veces
processed_repos: Dict[str, RepositoryResult] = {}  # Cache de repositorios procesados

# Crear lista de todos los paquetes que estamos buscando
target_package_names = [pkg["name"] for pkg in PACKAGES_TO_CHECK]

# Nuevo flujo: primero obtener todos los repositorios con package.json
print("\n🔍 Buscando repositorios con package.json...")
print("-" * 60)

repos_with_package_json = search_repositories_with_package_json()
print(f"✅ Encontrados {len(repos_with_package_json)} repositorios con package.json")

if not repos_with_package_json:
    print("❌ No se encontraron repositorios con package.json")
    exit(1)

# Procesar cada repositorio una sola vez
for r in repos_with_package_json:
    repo_id = r["repository"]["id"]
    repo_name = r["repository"]["name"]
    project = r["project"]["name"]
    path = r["path"]
    branch = r["versions"][0]["branchName"]
    
    repo_key = f"{project}/{repo_name}/{path}"
    
    print(f"\n📂 Analizando: {project}/{repo_name}")
    
    # Usar cache si ya descargamos este package.json
    if repo_key not in all_repos_data:
        items_url = f"https://dev.azure.com/{ORG}/{project}/_apis/git/repositories/{repo_id}/items"
        params: Dict[str, Any] = {
            "path": path,
            "versionDescriptor.version": branch,
            "includeContent": "true",
            "api-version": "7.1"
        }
        
        try:
            file_resp = requests.get(items_url, auth=auth, params=params)
            file_resp.raise_for_status()
            pkg_json = file_resp.json()
            
            deps: Dict[str, str] = pkg_json.get("dependencies", {})
            dev_deps: Dict[str, str] = pkg_json.get("devDependencies", {})
            all_deps: Dict[str, str] = {**deps, **dev_deps}
            
            # Obtener dependencias desde package-lock.json (o generarlo si no existe)
            print(f"    📄 Buscando o generando package-lock.json en {project}/{repo_name}...")
            lock_deps = get_lock_file_content(ORG, project, repo_id, branch, target_package_names, pkg_json)
            has_lock = len(lock_deps) > 0
            
            if has_lock:
                print(f"    ✅ Análisis completado - {len(lock_deps)} dependencias relevantes encontradas")
            else:
                print(f"    ⚠️  No se encontró package-lock.json")
            
            all_repos_data[repo_key] = RepoData(
                project=project,
                repo_name=repo_name,
                dependencies=all_deps,
                lock_dependencies=lock_deps,
                has_lock_file=has_lock
            )
        except Exception as e:
            print(f"[WARN] Error al procesar package.json en {project}/{repo_name}: {e}")
            continue
    
    # Inicializar registro del repositorio si no existe
    if repo_key not in processed_repos:
        processed_repos[repo_key] = RepositoryResult(
            project=all_repos_data[repo_key]["project"],
            repository_name=all_repos_data[repo_key]["repo_name"],
            path=path,
            has_package_lock=all_repos_data[repo_key]["has_lock_file"],
            direct_dependencies=[],
            transitive_dependencies=[]
        )
    
    # Ahora analizar cada paquete objetivo en este repositorio
    repo_data: RepoData = all_repos_data[repo_key]
    
    for package_info in PACKAGES_TO_CHECK:
        package_name = package_info["name"]
        target_version = package_info["target_version"]
        
        found_direct = package_name in repo_data["dependencies"]
        found_in_lock = package_name in repo_data["lock_dependencies"]
        
        if found_direct or found_in_lock:
            declared_range = ""  # Inicializar variable
            
            # Información de la dependencia directa
            if found_direct:
                declared_range = repo_data["dependencies"][package_name]
                is_vulnerable = is_version_vulnerable(target_version, declared_range)
                
                # Crear info de vulnerabilidad
                vuln_info: VulnerabilityInfo = {
                    "package_name": package_name,
                    "target_version": target_version,
                    "version_range": declared_range,
                    "actual_version": None,
                    "is_vulnerable": is_vulnerable,
                    "is_secure": not is_vulnerable,
                    "dependency_type": "DIRECTO"
                }
                
                processed_repos[repo_key]["direct_dependencies"].append(vuln_info)
                
                # Actualizar contadores
                if is_vulnerable:
                    scan_results["summary"]["total_vulnerable"] += 1
                else:
                    scan_results["summary"]["total_secure"] += 1
                scan_results["summary"]["total_direct_dependencies"] += 1
                
                status_icon = "⚠️" if is_vulnerable else "✔"
                status_text = f"VULNERABLE (incluye {target_version})" if is_vulnerable else f"SEGURO (no incluye {target_version})"
                
                print(f"    {status_icon} {package_name} {declared_range} → {status_text} [DIRECTO]")
            
            # Información de la subdependencia (si existe)
            if found_in_lock:
                versions_list = repo_data["lock_dependencies"][package_name]
                
                # Procesar CADA versión encontrada
                for actual_version in versions_list:
                    is_exact_vulnerable = is_version_vulnerable(target_version, f"={actual_version}")
                    
                    # Solo agregar si no es dependencia directa o si la versión es diferente del rango declarado
                    should_add = (
                        not found_direct or  # Siempre agregar si no es dependencia directa
                        (found_direct and not check_version_satisfies(actual_version, declared_range))  # O si la versión instalada no coincide con el rango declarado
                    )
                    
                    if should_add:
                        dependency_type = "TRANSITIVA" if not found_direct else "INSTALADA"
                        
                        vuln_info_lock: VulnerabilityInfo = {
                            "package_name": package_name,
                            "target_version": target_version,
                            "version_range": f"={actual_version}",
                            "actual_version": actual_version,
                            "is_vulnerable": is_exact_vulnerable,
                            "is_secure": not is_exact_vulnerable,
                            "dependency_type": dependency_type
                        }
                        
                        processed_repos[repo_key]["transitive_dependencies"].append(vuln_info_lock)
                        
                        # Actualizar contadores
                        if is_exact_vulnerable:
                            scan_results["summary"]["total_vulnerable"] += 1
                        else:
                            scan_results["summary"]["total_secure"] += 1
                        scan_results["summary"]["total_transitive_dependencies"] += 1
                        
                        lock_status_icon = "⚠️" if is_exact_vulnerable else "✔"
                        lock_status_text = f"VULNERABLE (es {target_version})" if is_exact_vulnerable else f"SEGURO (es {actual_version})"
                        
                        print(f"      {lock_status_icon} {package_name} ={actual_version} → {lock_status_text} [{dependency_type}]")

# Convertir repositorios procesados a lista
scan_results["repositories"] = list(processed_repos.values())
scan_results["total_repositories"] = len(scan_results["repositories"])

def save_results_to_json(scan_results: ScanResults, filename: str = "scan_results.json") -> None:
    """
    Guarda los resultados del escaneo en un archivo JSON.
    
    Args:
        scan_results: Resultados estructurados del escaneo
        filename: Nombre del archivo JSON a generar
    """
    try:
        with open(filename, 'w', encoding='utf-8') as f:
            json.dump(scan_results, f, indent=2, ensure_ascii=False)
        print(f"✅ Resultados guardados en {filename}")
    except Exception as e:
        print(f"❌ Error guardando JSON: {e}")

print("\n" + "="*80)
print("ESCANEO COMPLETADO")
print("="*80)

# Generar archivo JSON con los resultados
save_results_to_json(scan_results, "scan_results.json")

print(f"\n📊 RESUMEN:")
print(f"  • {scan_results['total_repositories']} repositorios analizados")
print(f"  • {scan_results['summary']['total_direct_dependencies']} dependencias directas")
print(f"  • {scan_results['summary']['total_transitive_dependencies']} dependencias transitivas")
print(f"  • {scan_results['summary']['total_vulnerable']} vulnerables ⚠️")
print(f"  • {scan_results['summary']['total_secure']} seguras ✔")
