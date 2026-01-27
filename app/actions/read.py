"""
read.py - Action de lecture de fichier
Fonctionne en local ET sur Azure grâce à l'abstraction storage.py

Usage:
    from actions.read import run
    result = run({"fichier": "data/contexte.txt"})
"""

from actions_config.common_header import *


def run(params: dict) -> dict:
    """
    Lit le contenu d'un fichier.
    
    Params:
        fichier (str): Chemin relatif du fichier à lire
        storage_type (str, optional): "file" ou "blob" (Azure seulement, défaut: "file")
    
    Returns:
        dict avec:
            - status: "success" ou "error"
            - fichier: chemin du fichier
            - contenu: contenu du fichier (si succès)
            - timestamp: horodatage UTC
            - error: message d'erreur (si échec)
    """
    fichier = params.get("fichier")
    storage_type = params.get("storage_type", "file")
    
    if not fichier:
        return {
            "status": "error",
            "error": "Paramètre 'fichier' manquant",
            "timestamp": get_timestamp()
        }
    
    # Résoudre le chemin (gère le préfixe USER_ID en mode Azure)
    fichier_path = resolve_path(fichier)
    
    try:
        contenu = read_file(fichier_path, storage_type)
        
        return {
            "status": "success",
            "fichier": fichier_path,
            "contenu": contenu,
            "timestamp": get_timestamp()
        }
    
    except FileNotFoundError:
        return {
            "status": "error",
            "error": f"Fichier non trouvé: {fichier_path}",
            "fichier": fichier_path,
            "timestamp": get_timestamp()
        }
    
    except Exception as e:
        return {
            "status": "error",
            "error": f"Erreur lors de la lecture: {str(e)}",
            "fichier": fichier_path,
            "timestamp": get_timestamp()
        }


# === TEST ===
if __name__ == "__main__":
    print("=== Test read.py ===\n")
    
    # Test 1: Lire un fichier existant
    print("1. Lecture de fenetre_active.txt...")
    result = run({"fichier": "data/fenetre_active.txt"})
    if result["status"] == "success":
        preview = result["contenu"][:100] + "..." if len(result["contenu"]) > 100 else result["contenu"]
        print(f"   ✅ Succès! Aperçu: {preview}\n")
    else:
        print(f"   ❌ Erreur: {result['error']}\n")
    
    # Test 2: Lire un fichier inexistant
    print("2. Lecture d'un fichier inexistant...")
    result = run({"fichier": "data/nexiste_pas.txt"})
    print(f"   → Status: {result['status']}")
    print(f"   → Erreur: {result.get('error', 'N/A')}\n")
    
    # Test 3: Paramètre manquant
    print("3. Appel sans paramètre 'fichier'...")
    result = run({})
    print(f"   → Status: {result['status']}")
    print(f"   → Erreur: {result.get('error', 'N/A')}\n")
    
    print("✅ Tests terminés!")