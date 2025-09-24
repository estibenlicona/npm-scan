# npm-scan

Utilidad para descubrir `package.json`/`package-lock.json` en repos, consolidar su contenido y auditar versiones objetivo de paquetes.

**Outputs Clave**

- Cache de trabajo en `.npm_scan_cache/` (se puede cambiar con `NPM_SCAN_CACHE_ROOT`).
- Reporte CSV consolidado: `.npm_scan_cache/package_lock_audit.csv`.
- Resumen visual en consola con métricas y enlace clicable al CSV.

**Ejecución Local**

```
python -m pip install -r requirements.txt
python -m unittest
python -m src.steps.step_01_get_repositories
python -m src.steps.step_02_get_packagesjson
python -m src.steps.step_03_get_package_lock
python -m src.steps.step_04_audit_package_locks --packages-file packages.txt
```

**Variables De Entorno**

- `AZURE_ORG`, `AZURE_PAT` o `SYSTEM_ACCESSTOKEN` para Azure DevOps.
- `AZURE_CODESEARCH_PAGE_SIZE` para la paginación del step 01.
- `NPM_SCAN_CACHE_ROOT` para cambiar la carpeta de cache.
- `NPM_PRIVATE_SCOPES` scopes privados omitidos al generar locks (por defecto `@appcross`).
- `NPM_SCAN_NPM_CACHE` ruta de cache de npm compartida (por defecto `.npm_scan_cache/npm-cache`).
- `NPM_REGISTRY` URL de registry/proxy npm (opcional).

**Azure Pipelines (Opcional)**

- `azure-pipelines.yml` incluye caches para pip y `.npm_scan_cache/` y publica el artefacto `audit_csv`.
- El parámetro `forceRefresh` fuerza recálculos; por defecto reutiliza cache.

**Reglas De Negocio**

- Repositorios objetivo
  - Step 01 usa Code Search con `filename:package.json` y pagina hasta agotar resultados.
  - Se conserva `repositoryId`, `project`, `branch` (de `versions[0].branchName`) y `path` al `package.json`.

- Identidad y cache
  - `repo_key` = `repositoryId|branch|path`.
  - Cada JSON se firma (SHA-256 estable) → “signature”.
  - Índices/manifest:
    - `package_json_repo_index.json`: `repo_key → { signature, repo metadata }`.
    - `package_lock_repo_index.json`: `repo_key → { lockSignature, packageSignature, source, repo metadata }`.
    - `package_lock_manifest.json`: `lockSignature → { path, repos[], packageSignatures[], sources[] }`.

- Obtención de `package-lock.json` (Step 03)
  - Se intenta descargar `package-lock.json` del repo (misma carpeta que `package.json`).
  - Si falta, se genera con `npm install --package-lock-only` en un directorio temporal.
  - Saneado previo al fallback:
    - Elimina `workspaces` y `overrides`.
    - Omite dependencias de scopes privados (`NPM_PRIVATE_SCOPES`, ej. `@appcross/*`).
    - Omite dependencias locales/git/url (`file:`, `link:`, `workspace:`, `git+`, `github:`, `http:`, `https:`).
  - Rendimiento:
    - Cache npm compartida en `.npm_scan_cache/npm-cache` (o `NPM_SCAN_NPM_CACHE`).
    - Flags: `--prefer-offline`, `--progress=false`, `--silent`, `--cache-min=86400`, `--no-audit`, `--no-fund`, `--ignore-scripts`, `--legacy-peer-deps`.
    - Reuso por firma: si otro repo tiene el mismo `package.json` (misma firma), se reutiliza el lock sin red ni npm.
  - `lock_source` indica `repository` (descargado) o `generated` (creado con npm).

- Auditoría (Step 04)
  - Aplana cada lock:
    - Lockfiles v2/v3 (`packages`): agrega `installed` por paquete y relaciones `dependency`, `dev`, `peer`, `optional` desde los campos de cada paquete.
    - Legacy (`dependencies`): agrega `installed` y relaciones `dependency` de `requires`, recursivo.
  - Directas vs transitivas:
    - Directas: aristas de primer nivel (dependency/dev/peer/optional) con `path` `"."` o vacío.
    - Transitivas: mismas categorías con otro `path`.
  - Paquetes objetivo (`packages.txt` o CSV con la primera columna):
    - Formato `name@version` (versión concreta, no rango).
    - `covered = true` si la versión objetivo está dentro del rango instalado (interpretado como “afectado”).
    - Estados: `covered`, `not_covered`, `invalid_current`, `invalid_target`, `no_target`.
  - Resumen visual en consola:
    - Tablas con KPIs (repos auditados, repos con riesgo, locks por fuente, paquetes, directas/transitivas) y tabla de estados.
    - `covered` en rojo (afectado); `not_covered` en verde.
    - Enlace clicable al CSV (OSC 8) y ruta absoluta.

**Paquetes Analizados**

- Para cada lock se generan filas únicas por `name`, `version`, `path`, `entry_type`:
  - `installed`: paquete instalado (incluye el root con `"."`).
  - `dependency`, `dev`, `peer`, `optional`: relaciones declaradas en el lock.
- `--include-all` ignora `packages.txt` y evalúa todo el lock.

**Columnas Del CSV**

- `project`, `repository`, `branch`, `package_json_path`, `repo_key`.
- `lock_signature`, `lock_source` (`repository`|`generated`), `package_lock_path`.
- `package_path`, `entry_type` (`installed`|`dependency`|`dev`|`peer`|`optional`|`root`).
- `package_name`, `current_spec`.
- `target_version`, `covered` (`true`=afectado), `status`.

**Archivo De Objetivos (`packages.txt`)**

- Una línea por paquete `name@version` (o CSV con esa cadena en la primera columna).
- Ejemplo: `left-pad@1.3.0`, `lodash@4.17.21`.

