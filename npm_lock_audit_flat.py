#!/usr/bin/env python3
import json
from pathlib import Path
from typing import Any, Dict, List, Union, Iterable, Optional, cast
import pandas as pd
from semantic_version import Version, NpmSpec  # type: ignore

def flatten_package_lock(lock_path: Union[str, Path] = "package-lock.json") -> List[Dict[str, str]]:
    """
    Lee un `package-lock.json` y devuelve una lista plana de paquetes (nombre, versión).

    Args:
        lock_path: Ruta al archivo package-lock.json (o Path)

    Returns:
        List[Dict[str,str]]: Lista de paquetes únicos con forma {"name": ..., "version": ...}
    """
    lock_file = Path(lock_path)
    if not lock_file.exists():
        raise FileNotFoundError(f"No se encontró {lock_file}")

    lock: Dict[str, Any] = cast(Dict[str, Any], json.loads(lock_file.read_text(encoding="utf-8")))
    packages: Dict[str, Any] = cast(Dict[str, Any], lock.get("packages")) or {}

    flat_packages: List[Dict[str, str]] = []

    for package, pkg_info in packages.items():


        if not package == "":

            version = pkg_info.get("version", "unknown")
            flat_packages.append({"name": package, "version": version})

            # Obtener dependencias transitivas
            dependencies: Dict[str, str] = cast(Dict[str, str], pkg_info.get("dependencies") or {})
            peer_dependencies: Dict[str, str] = cast(Dict[str, str], pkg_info.get("peerDependencies") or {})
            dev_dependencies: Dict[str, str] = cast(Dict[str, str], pkg_info.get("devDependencies") or {})

            for dep_name, dep_version in {**dependencies, **peer_dependencies, **dev_dependencies}.items():
                flat_packages.append({"name": dep_name, "version": dep_version})     

    # Eliminar duplicados preservando pares (name, version)
    unique_set = { (p["name"], p["version"]) for p in flat_packages }
    flat_unique = [{"name": n, "version": v} for (n, v) in sorted(unique_set)]

    print(f"Total paquetes únicos encontrados: {len(flat_unique)}")

    return flat_unique

def load_packages_from_file(file_path: Union[str, Path]) -> List[str]:
    """
    Carga una lista de paquetes desde un archivo CSV o TXT.
    El archivo puede tener una columna 'name' y 'target_version' (CSV) o líneas con 'name@version' (TXT).

    Args:
        file_path: Ruta al archivo (CSV o TXT)

    Returns:
        List[Dict[str,str]]: Lista de paquetes con forma {"name": ..., "target_version": ...}
    """
    path = Path(file_path)
    if not path.exists():
        raise FileNotFoundError(f"No se encontró {path}")

    packages: List[str] = []

    df: pd.DataFrame = pd.read_csv(path, header=None) # type: ignore
    packages = df[0].tolist()

    return packages

def parse_pkg_line(line: str) -> tuple[str, str]:
    """
    Acepta líneas tipo:
      - "tslib@2.8.1"
      - "@scope/pkg@^2.8.0"
      - "@scope/pkg@1.2.x"
      - "lodash@>=4 <5"
    Devuelve (nombre, spec) o None si no matchea.
    """
    line = line.strip()
    pkg, spec = line.rsplit("@", 1)
    name = pkg.split("/")[-1] if pkg.startswith("@") else pkg  # normaliza

    return name, spec

def build_targets_index(lines: Iterable[str]) -> Dict[str, str]:
    """
    Construye un índice {package_name -> spec} a partir del archivo packages.txt.
    En caso de duplicados, el último gana (o podrías acumular una lista si lo prefieres).
    """
    idx: Dict[str, str] = {}
    for ln in lines:
        parsed = parse_pkg_line(ln)
        if not parsed:
            continue
        name, spec = parsed
        idx[name] = spec
    return idx

def safe_npmspec(spec: str) -> Optional[NpmSpec]:
    """
    Envuelve la creación de NpmSpec para tolerar specs inválidos.
    """
    try:
        return NpmSpec(spec)
    except Exception:
        return None

def safe_version(ver: str) -> Optional[Version]:
    """
    Envuelve la creación de Version para tolerar versiones inválidas.
    """
    try:
        return Version.coerce(ver)  # type: ignore
    except Exception:
        return None

def main():
    packages: List[str] = load_packages_from_file("packages.txt")
    targets_idx: Dict[str, str] = build_targets_index(packages)

    packages_flat = flatten_package_lock("package-lock.json")


    for pkg in packages_flat:
        name = pkg.get("name", "")
        target = targets_idx.get(name)

        if not target:
            continue

        print(f"Buscando: {name} con spec '{spec}'")

if __name__ == "__main__":
    main()