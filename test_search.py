from main import load_packages_from_file, search_package_in_repos

print("🧪 Probando función con archivo de prueba...")
packages = load_packages_from_file('packages-test.txt')

print(f"\n📦 Paquetes cargados ({len(packages)} total):")
for i, pkg in enumerate(packages, 1):
    print(f"  {i}. {pkg['name']} @ {pkg['target_version']}")

print(f"\n🔍 Probando búsqueda...")
for pkg in packages:
    package_name = pkg['name']
    print(f"\n--- Buscando: {package_name} ---")
    try:
        results = search_package_in_repos(package_name)
        print(f"  Encontrados: {len(results)} repositorios")
        if len(results) > 0:
            print(f"  Primer resultado: {results[0]['repository']['name']}")
    except Exception as e:
        print(f"  Error: {e}")