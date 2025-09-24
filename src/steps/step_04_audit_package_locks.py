import csv
from collections import Counter
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Set, Tuple

import click
from semantic_version import NpmSpec, Version  # type: ignore

try:
    from .cache_utils import (
        CACHE_ROOT,
        load_index,
        load_json_document,
    )
except ImportError:
    from cache_utils import (
        CACHE_ROOT,
        load_index,
        load_json_document,
    )

PACKAGE_LOCK_SUBDIR = "package_lock"
PACKAGE_LOCK_REPO_INDEX_FILE = "package_lock_repo_index.json"
PACKAGE_LOCK_MANIFEST_FILE = "package_lock_manifest.json"
DEFAULT_TARGETS_FILE = "packages.txt"
DEFAULT_OUTPUT = CACHE_ROOT / "package_lock_audit.csv"


def load_target_lines(file_path: Path) -> List[str]:
    if not file_path.exists():
        raise FileNotFoundError(f"No se encontró el archivo de objetivos: {file_path}")

    if file_path.suffix.lower() == ".csv":
        lines: List[str] = []
        with file_path.open("r", encoding="utf-8", newline="") as handle:
            reader = csv.reader(handle)
            for row in reader:
                if not row:
                    continue
                cell = row[0].strip()
                if cell:
                    lines.append(cell)
        return lines

    return [
        line.strip()
        for line in file_path.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.strip().startswith("#")
    ]


def parse_pkg_line(line: str) -> Optional[Tuple[str, str]]:
    line = line.strip()
    if not line or line.startswith("#") or "@" not in line:
        return None
    try:
        name, spec = line.rsplit("@", 1)
    except ValueError:
        return None
    name = name.strip()
    spec = spec.strip()
    if not name or not spec:
        return None
    return name, spec


def build_targets_index(lines: Iterable[str]) -> Dict[str, str]:
    index: Dict[str, str] = {}
    for line in lines:
        parsed = parse_pkg_line(line)
        if not parsed:
            continue
        name, spec = parsed
        index[name] = spec
    return index


def safe_npmspec(spec: str) -> Optional[NpmSpec]:
    try:
        return NpmSpec(spec)
    except Exception:
        return None


def safe_version(version: str) -> Optional[Version]:
    try:
        return Version.coerce(version)  # type: ignore[attr-defined]
    except Exception:
        return None


def _normalize_spec_value(value: Any) -> str:
    if isinstance(value, dict):
        for key in ("version", "specifier", "range", "requested", "resolved"):
            candidate = value.get(key)
            if isinstance(candidate, str):
                return candidate
        return ""
    if value is None:
        return ""
    return str(value)


def _derive_package_name(package_path: str, pkg_info: Dict[str, Any]) -> str:
    name = pkg_info.get("name")
    if isinstance(name, str) and name:
        return name
    if not package_path:
        return "<root>"
    if "node_modules/" in package_path:
        return package_path.split("node_modules/")[-1] or package_path
    return package_path


def _iter_dependency_specs(pkg_info: Dict[str, Any]) -> Iterable[Tuple[str, str, str]]:
    mapping = (
        ("dependencies", "dependency"),
        ("peerDependencies", "peer"),
        ("devDependencies", "dev"),
    )
    for key, entry_type in mapping:
        deps = pkg_info.get(key)
        if isinstance(deps, dict):
            for dep_name, dep_spec in deps.items():
                if not isinstance(dep_name, str):
                    continue
                yield dep_name, _normalize_spec_value(dep_spec), entry_type


def _flatten_packages_map(packages: Dict[str, Any]) -> List[Dict[str, str]]:
    flat: List[Dict[str, str]] = []
    for package_path, pkg_info in packages.items():
        if not isinstance(pkg_info, dict):
            continue
        name = _derive_package_name(package_path, pkg_info)
        version = _normalize_spec_value(pkg_info.get("version")) or "unknown"
        path = package_path or "."
        flat.append(
            {
                "name": name,
                "version": version,
                "path": path,
                "entry_type": "installed",
            }
        )
        for dep_name, dep_spec, entry_type in _iter_dependency_specs(pkg_info):
            flat.append(
                {
                    "name": dep_name,
                    "version": dep_spec or "unknown",
                    "path": path,
                    "entry_type": entry_type,
                }
            )
    return flat


def _compose_legacy_path(parent_path: str, name: str) -> str:
    if not parent_path:
        return f"node_modules/{name}"
    return f"{parent_path}/node_modules/{name}"


def _flatten_legacy_dependencies(
    dependencies: Dict[str, Any], parent_path: str = ""
) -> List[Dict[str, str]]:
    flat: List[Dict[str, str]] = []
    for dep_name, dep_info in dependencies.items():
        if not isinstance(dep_name, str):
            continue
        path = _compose_legacy_path(parent_path, dep_name)
        if isinstance(dep_info, dict):
            version = _normalize_spec_value(dep_info.get("version")) or "unknown"
            flat.append(
                {
                    "name": dep_name,
                    "version": version,
                    "path": path,
                    "entry_type": "installed",
                }
            )
            requires = dep_info.get("requires")
            if isinstance(requires, dict):
                for req_name, req_spec in requires.items():
                    flat.append(
                        {
                            "name": req_name,
                            "version": _normalize_spec_value(req_spec) or "unknown",
                            "path": path,
                            "entry_type": "dependency",
                        }
                    )
            nested = dep_info.get("dependencies")
            if isinstance(nested, dict):
                flat.extend(_flatten_legacy_dependencies(nested, path))
        else:
            flat.append(
                {
                    "name": dep_name,
                    "version": _normalize_spec_value(dep_info) or "unknown",
                    "path": path,
                    "entry_type": "dependency",
                }
            )
    return flat


def flatten_package_lock_content(lock_content: Dict[str, Any]) -> List[Dict[str, str]]:
    flat: List[Dict[str, str]] = []
    packages = lock_content.get("packages")
    if isinstance(packages, dict) and packages:
        flat.extend(_flatten_packages_map(packages))
    else:
        dependencies = lock_content.get("dependencies")
        if isinstance(dependencies, dict):
            root_name = lock_content.get("name")
            root_version = _normalize_spec_value(lock_content.get("version"))
            if isinstance(root_name, str) and root_name:
                flat.append(
                    {
                        "name": root_name,
                        "version": root_version or "unknown",
                        "path": ".",
                        "entry_type": "root",
                    }
                )
            flat.extend(_flatten_legacy_dependencies(dependencies))
    seen = set()
    unique: List[Dict[str, str]] = []
    for pkg in flat:
        key = (pkg["name"], pkg["version"], pkg["path"], pkg.get("entry_type", ""))
        if key in seen:
            continue
        seen.add(key)
        unique.append(pkg)
    return unique


def filter_packages(
    packages: List[Dict[str, str]], targets_idx: Dict[str, str], include_all: bool
) -> List[Dict[str, str]]:
    if include_all or not targets_idx:
        return packages
    return [pkg for pkg in packages if pkg.get("name") in targets_idx]


def evaluate_packages(
    packages: List[Dict[str, str]], targets_idx: Dict[str, str]
) -> List[Dict[str, Any]]:
    results: List[Dict[str, Any]] = []
    for pkg in packages:
        name = pkg.get("name", "")
        current_spec = pkg.get("version", "")
        target_spec = targets_idx.get(name)
        status = "no_target"
        covered: Optional[bool] = None

        if target_spec:
            target_version = safe_version(target_spec)
            npmspec = safe_npmspec(current_spec)
            if target_version and npmspec:
                covered = target_version in npmspec
                status = "covered" if covered else "not_covered"
            elif target_version:
                current_version = safe_version(current_spec)
                if current_version is not None:
                    covered = current_version == target_version
                    status = "covered" if covered else "not_covered"
                else:
                    status = "invalid_current"
            else:
                status = "invalid_target"

        results.append(
            {
                "name": name,
                "current_spec": current_spec,
                "target_version": target_spec,
                "path": pkg.get("path", ""),
                "entry_type": pkg.get("entry_type", ""),
                "covered": covered,
                "status": status,
            }
        )
    return results


def write_report(rows: List[Dict[str, Any]], output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = [
        "project",
        "repository",
        "branch",
        "package_json_path",
        "repo_key",
        "lock_signature",
        "lock_source",
        "package_lock_path",
        "package_path",
        "entry_type",
        "package_name",
        "current_spec",
        "target_version",
        "covered",
        "status",
    ]
    with output_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            row_to_write = row.copy()
            covered_value = row_to_write.get("covered")
            if covered_value is True:
                row_to_write["covered"] = "true"
            elif covered_value is False:
                row_to_write["covered"] = "false"
            else:
                row_to_write["covered"] = ""
            writer.writerow(row_to_write)


@click.command(help="Step 04: Audita los package-lock cacheados y genera un informe consolidado")
@click.option(
    "--packages-file",
    default=DEFAULT_TARGETS_FILE,
    show_default=True,
    help="Archivo con la lista de paquetes objetivo (formato name@version).",
)
@click.option(
    "--output",
    default=str(DEFAULT_OUTPUT),
    show_default=True,
    help="Ruta del CSV de salida.",
)
@click.option(
    "--include-all",
    is_flag=True,
    help="Incluir paquetes que no estén en el archivo de objetivos.",
)
@click.option(
    "--force",
    is_flag=True,
    help="Opción reservada para compatibilidad; no tiene efecto.",
)
def run(packages_file: str, output: str, include_all: bool, force: bool) -> None:
    click.echo(f"[Info]: packages_file: {packages_file}")
    packages_path = Path(packages_file)
    try:
        target_lines = load_target_lines(packages_path)
    except FileNotFoundError as exc:
        raise click.ClickException(str(exc))

    targets_idx = build_targets_index(target_lines)

    if not targets_idx and not include_all:
        click.echo("[Warn] No se cargaron paquetes objetivo; se incluirán todos los paquetes.")
        include_all = True

    repo_index = load_index(PACKAGE_LOCK_REPO_INDEX_FILE)
    if not isinstance(repo_index, dict) or not repo_index:
        raise click.ClickException("No se encontro el indice de package-lock. Ejecuta step_03 previamente.")

    manifest = load_index(PACKAGE_LOCK_MANIFEST_FILE)
    if not isinstance(manifest, dict):
        manifest = {}

    if force:
        click.echo("[Info] --force no tiene efecto en este paso; se ignora.")

    rows: List[Dict[str, Any]] = []
    audited_repos: Set[str] = set()
    missing_locks: List[str] = []

    for repo_key, metadata in repo_index.items():
        if not isinstance(metadata, dict):
            continue
        lock_signature = metadata.get("lockSignature")
        if not isinstance(lock_signature, str) or not lock_signature:
            continue

        lock_content = load_json_document(PACKAGE_LOCK_SUBDIR, lock_signature)
        if lock_content is None:
            missing_locks.append(repo_key)
            continue
        if not isinstance(lock_content, dict):
            continue

        audited_repos.add(repo_key)
        flat_packages = flatten_package_lock_content(lock_content)
        selected_packages = filter_packages(flat_packages, targets_idx, include_all)
        evaluations = evaluate_packages(selected_packages, targets_idx)

        manifest_entry = manifest.get(lock_signature)
        lock_relative_path = ""
        if isinstance(manifest_entry, dict):
            lock_relative_path = manifest_entry.get("path", "") or ""
        if not lock_relative_path:
            lock_relative_path = f"{PACKAGE_LOCK_SUBDIR}/{lock_signature}.json"

        for evaluation in evaluations:
            rows.append(
                {
                    "project": metadata.get("project", ""),
                    "repository": metadata.get("repositoryName", ""),
                    "branch": metadata.get("branch", ""),
                    "package_json_path": metadata.get("path", ""),
                    "repo_key": repo_key,
                    "lock_signature": lock_signature,
                    "lock_source": metadata.get("source", ""),
                    "package_lock_path": lock_relative_path,
                    "package_path": evaluation.get("path", ""),
                    "entry_type": evaluation.get("entry_type", ""),
                    "package_name": evaluation.get("name", ""),
                    "current_spec": evaluation.get("current_spec", ""),
                    "target_version": evaluation.get("target_version") or "",
                    "covered": evaluation.get("covered"),
                    "status": evaluation.get("status", ""),
                }
            )

    write_report(rows, Path(output))

    repo_count = len(repo_index)
    stats = Counter(row["status"] for row in rows if row.get("status"))
    click.echo(
        f"Reporte generado en {output}. Registros: {len(rows)}. Repos auditados: {len(audited_repos)} / {repo_count}."
    )
    if stats:
        formatted = ", ".join(f"{key}: {value}" for key, value in stats.items())
        click.echo(f"Resumen por estado -> {formatted}")
    if missing_locks:
        click.echo(
            f"Locks ausentes o no accesibles para {len(missing_locks)} repos. Ejecuta step_03 si necesitas regenerarlos."
        )
    if not rows:
        click.echo("No se encontraron paquetes que cumplan los criterios seleccionados.")