"""
listdir.py - Action pour lister les fichiers d'un dossier
Fonctionne en local ET sur Azure grâce à l'abstraction storage.py

Utile pour voir les chunks dans le buffer, les fichiers de data, etc.

Usage:
    from actions.listdir import run
    result = run({"dossier": "buffer/"})
"""

from actions_config.common_header import *


def run(params: dict) -> dict:
    """
    Liste les fichiers dans un dossier.
    
    Params:
        dossier (str): Chemin relatif du dossier à lister
        storage_type (str, optional): "file" ou "blob" (Azure seulement, défaut: "file")
    
    Returns:
        dict avec:
            - status: "success" ou "error"
            - dossier: chemin du dossier
            - fichiers: liste des noms de fichiers
            - nombre: nombre de fichiers
            - timestamp: horodatage UTC
            - error: message d'erreur (si échec)
    """
    dossier = params.get("dossier")
    storage_type = params.get("storage_type", "file")
    
    if not dossier:
        return {
            "status": "error",
            "error": "Paramètre 'dossier' manquant",
            "timestamp": get_timestamp()
        }
    
    # Résoudre le chemin (gère le préfixe USER_ID en mode Azure)
    dossier_path = resolve_path(dossier)
    
    try:
        fichiers = list_files(dossier_path, storage_type)
        
        # Filtrer les fichiers cachés (commencent par .)
        fichiers_visibles = [f for f in fichiers if not f.startswith('.')]
        
        return {
            "status": "success",
            "dossier": dossier_path,
            "fichiers": fichiers_visibles,
            "nombre": len(fichiers_visibles),
            "timestamp": get_timestamp()
        }
    
    except Exception as e:
        return {
            "status": "error",
            "error": f"Erreur lors du listage: {str(e)}",
            "dossier": dossier_path,
            "timestamp": get_timestamp()
        }


# === TEST ===
if __name__ == "__main__":
    print("=== Test listdir.py ===\n")
    
    # Test 1: Lister le dossier data/
    print("1. Listage de data/...")
    result = run({"dossier": "data/"})
    print(f"   → Status: {result['status']}")
    print(f"   → Nombre de fichiers: {result.get('nombre', 0)}")
    print(f"   → Fichiers: {result.get('fichiers', [])}\n")
    
    # Test 2: Lister le dossier buffer/
    print("2. Listage de buffer/...")
    result = run({"dossier": "buffer/"})
    print(f"   → Status: {result['status']}")
    print(f"   → Nombre de fichiers: {result.get('nombre', 0)}")
    print(f"   → Fichiers: {result.get('fichiers', [])}\n")
    
    # Test 3: Lister un dossier inexistant
    print("3. Listage d'un dossier inexistant...")
    result = run({"dossier": "dossier_inexistant/"})
    print(f"   → Status: {result['status']}")
    print(f"   → Nombre de fichiers: {result.get('nombre', 0)}")
    print(f"   → Fichiers: {result.get('fichiers', [])}\n")
    
    # Test 4: Paramètre manquant
    print("4. Appel sans paramètre 'dossier'...")
    result = run({})
    print(f"   → Status: {result['status']}")
    print(f"   → Erreur: {result.get('error', 'N/A')}\n")
    
    print("✅ Tests terminés!")