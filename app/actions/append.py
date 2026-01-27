"""
append.py - Action d'ajout de contenu à un fichier
Fonctionne en local ET sur Azure grâce à l'abstraction storage.py

Usage:
    from actions.append import run
    result = run({"fichier": "data/log.txt", "contenu": "Nouvelle entrée"})
"""

from actions_config.common_header import *


def run(params: dict) -> dict:
    """
    Ajoute du contenu à la fin d'un fichier existant.
    Crée le fichier s'il n'existe pas.
    
    Params:
        fichier (str): Chemin relatif du fichier
        contenu (str): Contenu à ajouter à la fin
        storage_type (str, optional): "file" ou "blob" (Azure seulement, défaut: "file")
    
    Returns:
        dict avec:
            - status: "success" ou "error"
            - message: description de l'action
            - fichier: chemin du fichier
            - taille_ajoutee: nombre de caractères ajoutés
            - timestamp: horodatage UTC
            - error: message d'erreur (si échec)
    """
    fichier = params.get("fichier")
    contenu = params.get("contenu")
    storage_type = params.get("storage_type", "file")
    
    if not fichier:
        return {
            "status": "error",
            "error": "Paramètre 'fichier' manquant",
            "timestamp": get_timestamp()
        }
    
    if contenu is None:
        return {
            "status": "error",
            "error": "Paramètre 'contenu' manquant",
            "timestamp": get_timestamp()
        }
    
    # Résoudre le chemin (gère le préfixe USER_ID en mode Azure)
    fichier_path = resolve_path(fichier)
    
    try:
        result = append_file(fichier_path, contenu, storage_type)
        
        return {
            "status": "success",
            "message": f"Contenu ajouté au fichier « {fichier_path} ».",
            "fichier": fichier_path,
            "taille_ajoutee": len(contenu),
            "timestamp": get_timestamp()
        }
    
    except Exception as e:
        return {
            "status": "error",
            "error": f"Erreur lors de l'ajout: {str(e)}",
            "fichier": fichier_path,
            "timestamp": get_timestamp()
        }


# === TEST ===
if __name__ == "__main__":
    print("=== Test append.py ===\n")
    
    # Test 1: Créer un fichier via append (fichier n'existe pas)
    print("1. Append sur fichier inexistant (création)...")
    result = run({
        "fichier": "data/test_append.txt",
        "contenu": "Première ligne\n"
    })
    print(f"   → Status: {result['status']}")
    print(f"   → Message: {result.get('message', result.get('error'))}\n")
    
    # Test 2: Ajouter du contenu
    print("2. Ajout de contenu...")
    result = run({
        "fichier": "data/test_append.txt",
        "contenu": "Deuxième ligne\n"
    })
    print(f"   → Status: {result['status']}")
    print(f"   → Taille ajoutée: {result.get('taille_ajoutee', 'N/A')} caractères\n")
    
    # Test 3: Encore un ajout
    print("3. Encore un ajout...")
    result = run({
        "fichier": "data/test_append.txt",
        "contenu": "Troisième ligne\n"
    })
    print(f"   → Status: {result['status']}\n")
    
    # Test 4: Vérifier le contenu final
    print("4. Vérification du contenu final...")
    from actions.read import run as read_run
    result = read_run({"fichier": "data/test_append.txt"})
    if result["status"] == "success":
        print(f"   ✅ Contenu:\n{result['contenu']}")
    else:
        print(f"   ❌ Erreur: {result['error']}\n")
    
    # Test 5: Paramètre manquant
    print("5. Appel sans paramètre 'contenu'...")
    result = run({"fichier": "data/test.txt"})
    print(f"   → Status: {result['status']}")
    print(f"   → Erreur: {result.get('error', 'N/A')}\n")
    
    # Nettoyage
    print("6. Nettoyage du fichier test...")
    delete_file("data/test_append.txt")
    print("   → Fichier supprimé\n")
    
    print("✅ Tests terminés!")