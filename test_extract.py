import json
from main import extract_filtered_dependencies_from_lock

# Cargar el package-lock.json que proporcionaste
package_lock_path = r"c:\Users\estib\AppData\Local\Temp\npm_scan_am2577kv\package-lock.json"

print("🧪 Probando extracción de dependencias múltiples...")

try:
    with open(package_lock_path, 'r', encoding='utf-8') as f:
        lock_content = json.load(f)
    
    # Buscar específicamente tslib para ver si encuentra múltiples versiones
    target_packages = ["tslib"]
    
    print(f"📦 Buscando paquetes: {', '.join(target_packages)}")
    print(f"📄 Archivo: {package_lock_path}")
    
    # Primero, veamos cuántas veces aparece tslib en el archivo
    lock_str = json.dumps(lock_content)
    tslib_count = lock_str.count('"tslib"')
    print(f"🔍 'tslib' aparece {tslib_count} veces en el archivo")
    
    # Ahora veamos si nuestro filtro lo encuentra
    filtered_deps = extract_filtered_dependencies_from_lock(lock_content, target_packages)
    
    print(f"\n✅ Resultados de la extracción:")
    for package_name, versions in filtered_deps.items():
        print(f"  📋 {package_name}:")
        for version in sorted(versions):  # Ordenar para mejor visualización
            print(f"    └─ {version}")
        print(f"    Total versiones: {len(versions)}")
    
    if not filtered_deps:
        print("  ❌ No se encontraron dependencias")
        
        # Debug: veamos qué hay en packages
        if "packages" in lock_content:
            print(f"\n� Debug - Buscando manualmente en packages:")
            packages = lock_content["packages"]
            found_tslib = []
            for path, info in packages.items():
                if "tslib" in path:
                    version = info.get("version", "unknown")
                    print(f"    📍 Encontrado en: {path} → {version}")
                    found_tslib.append((path, version))
                    
                # También buscar en dependencies
                for dep_type in ["dependencies", "peerDependencies", "devDependencies"]:
                    if dep_type in info and "tslib" in info[dep_type]:
                        range_spec = info[dep_type]["tslib"]
                        print(f"    🔗 Referenciado en {path} ({dep_type}): {range_spec}")
            
            print(f"  Total referencias directas encontradas: {len(found_tslib)}")
    
    print(f"\n�📊 Resumen:")
    print(f"  • Paquetes encontrados: {len(filtered_deps)}")
    total_versions = sum(len(versions) for versions in filtered_deps.values())
    print(f"  • Total de versiones: {total_versions}")

except FileNotFoundError:
    print(f"❌ No se encontró el archivo: {package_lock_path}")
except Exception as e:
    print(f"❌ Error: {e}")
    import traceback
    traceback.print_exc()