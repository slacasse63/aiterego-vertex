"""
write.py - Action d'écriture de fichier
Fonctionne en local ET sur Azure grâce à l'abstraction storage.py

Usage:
    from actions.write import run
    result = run({"fichier": "data/test.txt", "contenu": "Hello world!"})
"""

from actions_config.common_header import *


def run(params: dict) -> dict:
    """
    Écrit (ou réécrit) un fichier avec le contenu spécifié.
    Crée le fichier et les dossiers parents s'ils n'existent pas.
    
    Params:
        fichier (str): Chemin relatif du fichier à écrire
        contenu (str): Contenu à écrire dans le fichier
        storage_type (str, optional): "file" ou "blob" (Azure seulement, défaut: "file")
    
    Returns:
        dict avec:
            - status: "success" ou "error"
            - message: description de l'action
            - fichier: chemin du fichier
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
        result = write_file(fichier_path, contenu, storage_type)
        
        return {
            "status": "success",
            "message": f"Le fichier « {fichier_path} » a été écrit avec succès.",
            "fichier": fichier_path,
            "taille": len(contenu),
            "timestamp": get_timestamp()
        }
    
    except Exception as e:
        return {
            "status": "error",
            "error": f"Erreur lors de l'écriture: {str(e)}",
            "fichier": fichier_path,
            "timestamp": get_timestamp()
        }


# === TEST ===
if __name__ == "__main__":
    print("=== Test write.py ===\n")
    
    # Test 1: Écrire un nouveau fichier
    print("1. Écriture d'un fichier test...")
    result = run({
        "fichier": "data/test_write.txt",
        "contenu": "Ceci est un test d'écriture.\nDeuxième ligne."
    })
    print(f"   → Status: {result['status']}")
    print(f"   → Message: {result.get('message', result.get('error'))}")
    print(f"   → Taille: {result.get('taille', 'N/A')} caractères\n")
    
    # Test 2: Vérifier en relisant
    print("2. Vérification par lecture...")
    from actions.read import run as read_run
    result = read_run({"fichier": "data/test_write.txt"})
    if result["status"] == "success":
        print(f"   ✅ Contenu lu: {result['contenu']}\n")
    else:
        print(f"   ❌ Erreur: {result['error']}\n")
    
    # Test 3: Réécrire (overwrite)
    print("3. Réécriture du même fichier...")
    result = run({
        "fichier": "data/test_write.txt",
        "contenu": "Contenu remplacé!"
    })
    print(f"   → Status: {result['status']}")
    result = read_run({"fichier": "data/test_write.txt"})
    print(f"   → Nouveau contenu: {result.get('contenu', 'N/A')}\n")
    
    # Test 4: Paramètre manquant
    print("4. Appel sans paramètre 'contenu'...")
    result = run({"fichier": "data/test.txt"})
    print(f"   → Status: {result['status']}")
    print(f"   → Erreur: {result.get('error', 'N/A')}\n")
    
    # Nettoyage
    print("5. Nettoyage du fichier test...")
    delete_file("data/test_write.txt")
    print("   → Fichier supprimé\n")
    
    print("✅ Tests terminés!")