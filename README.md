# npm-scan

## Azure Pipelines

1. Crea un pipeline en Azure DevOps apuntando a `azure-pipelines.yml`.
2. Declara las variables requeridas en el pipeline:
   - `AZURE_ORG`: nombre de la organizacion de Azure DevOps (ej. `flujodetrabajot`).
   - `AZURE_PAT` (secreta): token con permisos para Code Search y repos.
   - Opcional `AZURE_CODESEARCH_PAGE_SIZE` para ajustar el tamanio de pagina.
3. Ajusta el parametro `forceRefresh` (boolean) si deseas forzar la regeneracion de caches; por defecto esta deshabilitado para reutilizar artefactos previos.
4. El pipeline usa dos caches:
   - `$(Pipeline.Workspace)/.pip` para dependencias de pip.
   - `$(Build.SourcesDirectory)/.npm_scan_cache` para los artefactos de los steps.
5. Los resultados se publican como artefacto `npm_scan_cache` al final del job.

## Ejecucion local

```
python -m pip install -r requirements.txt
python -m unittest
python -m src.steps.step_01_get_repositories --force
python -m src.steps.step_02_get_packagesjson --force
python -m src.steps.step_03_get_package_lock --force
python -m src.steps.step_04_audit_package_locks --packages-file packages.txt
```

Variables de entorno utiles:

- `AZURE_ORG`, `AZURE_PAT` o `SYSTEM_ACCESSTOKEN` para autenticacion.
- `AZURE_CODESEARCH_PAGE_SIZE` para definir la paginacion del step 01.
- `NPM_SCAN_CACHE_ROOT` para sobreescribir la ubicacion de la cache.
