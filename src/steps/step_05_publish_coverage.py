from __future__ import annotations

import csv
import os
import time
from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, List

import click

try:
    from .cache_utils import CACHE_ROOT
except ImportError:
    from cache_utils import CACHE_ROOT  # type: ignore


def _read_csv(csv_path: Path) -> List[Dict[str, Any]]:
    if not csv_path.exists():
        raise click.ClickException(f"No se encontró el CSV de auditoría: {csv_path}")
    with csv_path.open("r", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        return [dict(row) for row in reader]


def _group_by_repository(rows: List[Dict[str, Any]]) -> Dict[str, List[Dict[str, Any]]]:
    groups: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for row in rows:
        repo = row.get("repository") or row.get("repositoryName") or row.get("repo_key") or "<desconocido>"
        groups[str(repo)].append(row)
    return groups


def _boolish(val: Any) -> bool:
    if isinstance(val, bool):
        return val
    if isinstance(val, str):
        return val.strip().lower() in {"true", "1", "yes", "y", "si"}
    return False


def build_html(rows: List[Dict[str, Any]], out_dir: Path) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    index = out_dir / "index.html"

    groups = _group_by_repository(rows)

    style = """
    <style>
      body { font-family: Arial, sans-serif; margin: 16px; }
      table { border-collapse: collapse; width: 100%; margin: 8px 0 16px 0; }
      th, td { border: 1px solid #ddd; padding: 6px 8px; font-size: 13px; }
      th { background: #f2f2f2; text-align: left; }
      tr.malicious { background: #ffe5e5; }
      .meta { color: #555; font-size: 12px; }
      details { margin-bottom: 10px; }
      summary { cursor: pointer; font-weight: bold; }
    </style>
    """

    header = """
    <h2>Resultado de Auditoría de package-lock</h2>
    <p class="meta">Generado por step_05_publish_coverage.</p>
    """

    columns = [
        "project",
        "repository",
        "branch",
        "package_json_path",
        "package_name",
        "entry_type",
        "package_path",
        "current_spec",
        "target_version",
        "status",
        "covered",
    ]

    rows_html: List[str] = ["<html><head><meta charset=\"utf-8\">", style, "</head><body>", header]

    # Resumen
    total = len(rows)
    covered_count = sum(1 for r in rows if str(r.get("covered", "")).lower() in {"true", "1"})
    not_covered = sum(1 for r in rows if str(r.get("status", "")).lower() == "not_covered")
    rows_html.append(f"<p class=\"meta\">Registros: {total} — Cubiertos: {covered_count} — No cubiertos: {not_covered}</p>")

    # Por repositorio
    for repo, repo_rows in sorted(groups.items(), key=lambda x: x[0].lower()):
        proj = repo_rows[0].get("project", "")
        branch = repo_rows[0].get("branch", "")
        rows_html.append(f"<details open><summary>{repo} <span class=\"meta\">(proyecto: {proj} — rama: {branch} — {len(repo_rows)} registros)</span></summary>")
        rows_html.append("<table>")
        # header
        rows_html.append("<tr>" + "".join(f"<th>{c}</th>" for c in columns) + "</tr>")
        # body
        for r in repo_rows:
            # Considerar 'status == not_covered' como malicioso para resaltar
            is_mal = str(r.get("status", "")).lower() == "not_covered" or _boolish(r.get("is_malicious"))
            cls = " class=\"malicious\"" if is_mal else ""
            rows_html.append("<tr" + cls + ">" + "".join(f"<td>{(r.get(c, '') or '')}</td>" for c in columns) + "</tr>")
        rows_html.append("</table></details>")

    rows_html.append("</body></html>")
    index.write_text("\n".join(rows_html), encoding="utf-8")
    return index


def build_cobertura_xml(summary_path: Path) -> Path:
    summary_path.parent.mkdir(parents=True, exist_ok=True)
    ts = int(time.time())
    xml = f"""
<coverage lines-valid=\"1\" lines-covered=\"1\" line-rate=\"1.0\" branch-rate=\"0.0\" version=\"1.9\" timestamp=\"{ts}\">
  <sources>
    <source>.</source>
  </sources>
  <packages>
    <package name=\"audit\" line-rate=\"1.0\" branch-rate=\"0.0\" complexity=\"0.0\">
      <classes>
        <class name=\"report\" filename=\"report-html/index.html\" line-rate=\"1.0\" branch-rate=\"0.0\">
          <lines>
            <line number=\"1\" hits=\"1\"/>
          </lines>
        </class>
      </classes>
    </package>
  </packages>
</coverage>
""".strip()
    summary_path.write_text(xml, encoding="utf-8")
    return summary_path


@click.command(help="Step 05: Genera HTML y Cobertura XML a partir del CSV de auditoría")
@click.option("--csv-path", default=str(CACHE_ROOT / "package_lock_audit.csv"), show_default=True)
@click.option("--out-dir", default=str(CACHE_ROOT / "report-html"), show_default=True)
@click.option("--summary-xml", default=str(CACHE_ROOT / "report-html" / "cobertura.xml"), show_default=True)
def run(csv_path: str, out_dir: str, summary_xml: str) -> None:
    rows = _read_csv(Path(csv_path))
    html = build_html(rows, Path(out_dir))
    cov = build_cobertura_xml(Path(summary_xml))
    click.echo(f"[Info] HTML generado en: {html}")
    click.echo(f"[Info] Cobertura (Cobertura XML) generado en: {cov}")


if __name__ == "__main__":
    run()

