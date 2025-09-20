import sys
import os
sys.path.append(os.getcwd())

from main import extract_filtered_dependencies_from_lock

def test_extract_filtered_dependencies_from_lock():
    """
    Test unitario para verificar que se extraen TODAS las versiones de cada paquete.
    """
    print("🧪 TEST: extract_filtered_dependencies_from_lock")
    print("=" * 60)
    
    # Mock de package-lock.json que simula el caso real con múltiples versiones de tslib
    test_lock_content = {
        "name": "test-project",
        "lockfileVersion": 3,
        "packages": {
            "": {
                "dependencies": {
                    "@angular/platform-browser": "^8.1.3"
                }
            },
            # tslib versión 1 en la raíz
            "node_modules/tslib": {
                "version": "1.14.1",
                "license": "0BSD"
            },
            # @angular/platform-browser que depende de tslib
            "node_modules/@angular/platform-browser": {
                "version": "8.1.3",
                "dependencies": {
                    "tslib": "^1.9.0"
                },
                "peerDependencies": {
                    "@angular/common": "8.1.3",
                    "@angular/core": "8.1.3"
                }
            },
            # tslib versión 2 en un subdirectorio
            "node_modules/@angular/platform-browser/node_modules/tslib": {
                "version": "1.10.0",
                "license": "0BSD"
            },
            # @angular/core que también depende de tslib
            "node_modules/@angular/core": {
                "version": "8.1.3",
                "dependencies": {
                    "tslib": "^1.9.0"
                }
            },
            # tslib versión 3 en otro subdirectorio
            "node_modules/@angular/core/node_modules/tslib": {
                "version": "1.11.2",
                "license": "0BSD"
            },
            # Otro paquete que depende de tslib
            "node_modules/some-other-package": {
                "version": "2.0.0",
                "dependencies": {
                    "tslib": "^1.13.0"
                }
            }
        }
    }
    
    target_packages = ["tslib"]
    
    print(f"📦 Buscando: {target_packages}")
    print(f"📄 Package-lock.json simulado con {len(test_lock_content['packages'])} entradas")
    
    # Primero, veamos manualmente cuántas versiones de tslib hay
    print(f"\n🔍 ANÁLISIS MANUAL del package-lock:")
    tslib_entries = []
    for path, info in test_lock_content["packages"].items():
        if "tslib" in path and path != "":
            version = info.get("version", "unknown")
            tslib_entries.append((path, version))
            print(f"  📍 {path} → {version}")
        
        # También buscar en dependencies
        for dep_type in ["dependencies", "peerDependencies", "devDependencies"]:
            if dep_type in info and "tslib" in info[dep_type]:
                range_spec = info[dep_type]["tslib"]
                print(f"  🔗 Referenciado en {path} ({dep_type}): {range_spec}")
    
    print(f"  Total entradas directas de tslib: {len(tslib_entries)}")
    
    # Ahora probemos nuestra función
    print(f"\n🧪 EJECUTANDO extract_filtered_dependencies_from_lock...")
    result = extract_filtered_dependencies_from_lock(test_lock_content, target_packages)
    
    print(f"\n✅ RESULTADOS:")
    for package_name, versions in result.items():
        print(f"  📋 {package_name}: {len(versions)} versiones")
        for version in sorted(versions):
            print(f"    └─ {version}")
    
    # Verificar resultados
    print(f"\n🔍 VERIFICACIÓN:")
    expected_tslib_versions = ["1.14.1", "1.10.0", "1.11.2"]
    
    if "tslib" in result:
        found_versions = sorted(result["tslib"])
        expected_sorted = sorted(expected_tslib_versions)
        
        print(f"  Esperado: {expected_sorted}")
        print(f"  Encontrado: {found_versions}")
        
        missing_versions = set(expected_sorted) - set(found_versions)
        extra_versions = set(found_versions) - set(expected_sorted)
        
        if missing_versions:
            print(f"  ❌ Versiones faltantes: {missing_versions}")
        if extra_versions:
            print(f"  ℹ️  Versiones extra: {extra_versions}")
        
        if found_versions == expected_sorted:
            print(f"  ✅ ÉXITO: Se encontraron todas las versiones esperadas")
            return True
        else:
            print(f"  ❌ FALLO: No se encontraron todas las versiones")
            return False
    else:
        print(f"  ❌ FALLO: No se encontró tslib en los resultados")
        return False

if __name__ == "__main__":
    success = test_extract_filtered_dependencies_from_lock()
    if success:
        print(f"\n🎉 Test pasó correctamente")
        exit(0)
    else:
        print(f"\n💥 Test falló")
        exit(1)