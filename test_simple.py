import sys
import os

# Agregar el directorio actual al path para importar main
sys.path.append(os.getcwd())

from main import extract_filtered_dependencies_from_lock

# Crear un package-lock.json de prueba simplificado basado en el ejemplo que mostraste
test_lock_content = {
    "name": "test-project",
    "lockfileVersion": 3,
    "packages": {
        "": {
            "dependencies": {
                "@angular/platform-browser": "^8.1.3"
            }
        },
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
        "node_modules/tslib": {
            "version": "1.14.1"
        },
        "node_modules/@angular/common": {
            "version": "8.1.3", 
            "dependencies": {
                "tslib": "^1.9.0"
            }
        },
        "node_modules/@angular/core": {
            "version": "8.1.3",
            "dependencies": {
                "tslib": "^1.9.0"
            }
        },
        "node_modules/@angular/common/node_modules/tslib": {
            "version": "1.10.0"
        }
    }
}

print("🧪 Probando con package-lock.json de prueba...")

# Buscar tslib y @angular/core
target_packages = ["tslib", "@angular/core", "@angular/platform-browser"]

print(f"📦 Buscando paquetes: {', '.join(target_packages)}")

filtered_deps = extract_filtered_dependencies_from_lock(test_lock_content, target_packages)

print(f"\n✅ Resultados:")
for package_name, versions in filtered_deps.items():
    print(f"  📋 {package_name}:")
    for version in sorted(versions):
        print(f"    └─ {version}")
    print(f"    Total versiones: {len(versions)}")

print(f"\n📊 Resumen:")
print(f"  • Paquetes encontrados: {len(filtered_deps)}")
total_versions = sum(len(versions) for versions in filtered_deps.values())
print(f"  • Total de versiones: {total_versions}")

# Verificar resultados esperados
expected_results = {
    "tslib": 2,  # Debería encontrar al menos 2 versiones
    "@angular/core": 1,
    "@angular/platform-browser": 1
}

print(f"\n🔍 Verificación:")
success = True
for pkg, expected_count in expected_results.items():
    if pkg in filtered_deps:
        found_count = len(filtered_deps[pkg])
        if found_count >= expected_count:
            print(f"  ✅ {pkg}: {found_count} versiones (esperado mínimo {expected_count})")
        else:
            print(f"  ❌ {pkg}: {found_count} versiones (esperado mínimo {expected_count})")
            success = False
    else:
        print(f"  ❌ {pkg}: no encontrado")
        success = False

if success:
    print(f"\n🎉 ¡Todas las pruebas pasaron!")
else:
    print(f"\n💥 Algunas pruebas fallaron")