from main import load_packages_from_file

print("🧪 Probando función de parsing...")
packages = load_packages_from_file('packages.txt')

print(f"\nTotal: {len(packages)} paquetes")
print("\nPrimeros 10 paquetes parseados:")
for i, pkg in enumerate(packages[:10], 1):
    print(f"  {i:2}. {pkg['name']} @ {pkg['target_version']}")

if len(packages) > 10:
    print(f"\n... y {len(packages)-10} más")