"""
search.py - Action de recherche dans un fichier
Fonctionne en local ET sur Azure grâce à l'abstraction storage.py

CLÉ POUR LE RAG: Cette action permet de chercher dans le buffer
et la fenêtre de contexte pour retrouver des informations passées.

Usage:
    from actions.search import run
    result = run({"fichier": "buffer/chunk_xxx.txt", "mot": "vectalisation"})
"""

from actions_config.common_header import *


def run(params: dict) -> dict:
    """
    Recherche un mot ou une phrase dans un fichier.
    Retourne toutes les lignes contenant le terme recherché.
    
    Params:
        fichier (str): Chemin relatif du fichier à fouiller
        mot (str): Mot ou phrase à rechercher (insensible à la casse)
        storage_type (str, optional): "file" ou "blob" (Azure seulement, défaut: "file")
    
    Returns:
        dict avec:
            - status: "success" ou "error"
            - fichier: chemin du fichier
            - mot: terme recherché
            - occurrences: nombre de lignes trouvées
            - resultats: liste de {ligne: numéro, contenu: texte}
            - timestamp: horodatage UTC
            - error: message d'erreur (si échec)
    """
    fichier = params.get("fichier")
    mot = params.get("mot")
    storage_type = params.get("storage_type", "file")
    
    if not fichier:
        return {
            "status": "error",
            "error": "Paramètre 'fichier' manquant",
            "timestamp": get_timestamp()
        }
    
    if not mot:
        return {
            "status": "error",
            "error": "Paramètre 'mot' manquant",
            "timestamp": get_timestamp()
        }
    
    # Résoudre le chemin (gère le préfixe USER_ID en mode Azure)
    fichier_path = resolve_path(fichier)
    
    try:
        # Lire le fichier
        contenu = read_file(fichier_path, storage_type)
        lignes = contenu.splitlines()
        
        # Recherche insensible à la casse
        mot_lower = mot.lower()
        resultats = [
            {"ligne": i + 1, "contenu": ligne}
            for i, ligne in enumerate(lignes)
            if mot_lower in ligne.lower()
        ]
        
        return {
            "status": "success",
            "fichier": fichier_path,
            "mot": mot,
            "occurrences": len(resultats),
            "resultats": resultats,
            "timestamp": get_timestamp()
        }
    
    except FileNotFoundError:
        return {
            "status": "error",
            "error": f"Fichier non trouvé: {fichier_path}",
            "fichier": fichier_path,
            "mot": mot,
            "timestamp": get_timestamp()
        }
    
    except Exception as e:
        return {
            "status": "error",
            "error": f"Erreur lors de la recherche: {str(e)}",
            "fichier": fichier_path,
            "mot": mot,
            "timestamp": get_timestamp()
        }


def search_in_directory(directory: str, mot: str, storage_type: str = "file") -> dict:
    """
    Recherche un mot dans TOUS les fichiers d'un dossier.
    Utile pour chercher dans tout le buffer d'un coup.
    
    Params:
        directory (str): Chemin du dossier à fouiller
        mot (str): Mot ou phrase à rechercher
        storage_type (str): "file" ou "blob"
    
    Returns:
        dict avec résultats par fichier
    """
    try:
        fichiers = list_files(directory, storage_type)
        
        all_results = []
        total_occurrences = 0
        
        for fichier in fichiers:
            # Ignorer les fichiers cachés
            if fichier.startswith('.'):
                continue
                
            fichier_path = f"{directory.rstrip('/')}/{fichier}"
            result = run({
                "fichier": fichier_path,
                "mot": mot,
                "storage_type": storage_type
            })
            
            if result["status"] == "success" and result["occurrences"] > 0:
                all_results.append({
                    "fichier": fichier,
                    "occurrences": result["occurrences"],
                    "resultats": result["resultats"]
                })
                total_occurrences += result["occurrences"]
        
        return {
            "status": "success",
            "directory": directory,
            "mot": mot,
            "fichiers_trouves": len(all_results),
            "total_occurrences": total_occurrences,
            "resultats": all_results,
            "timestamp": get_timestamp()
        }
    
    except Exception as e:
        return {
            "status": "error",
            "error": f"Erreur lors de la recherche dans le dossier: {str(e)}",
            "directory": directory,
            "mot": mot,
            "timestamp": get_timestamp()
        }


# === TEST ===
if __name__ == "__main__":
    print("=== Test search.py ===\n")
    
    # Créer un fichier de test avec du contenu
    print("0. Préparation: création d'un fichier test...")
    test_content = """Ligne 1: Introduction à AIter Ego
Ligne 2: La vectalisation est un processus clé
Ligne 3: Le buffer stocke les fenêtres terminées
Ligne 4: MOSS signifie Modular Orchestrated Storage System
Ligne 5: La vectalisation transforme le texte en vecteurs
Ligne 6: Hermès gère la recherche sémantique
Ligne 7: Le Scribe fait la vectalisation
"""
    write_file("data/test_search.txt", test_content)
    print("   → Fichier créé\n")
    
    # Test 1: Recherche simple
    print("1. Recherche de 'vectalisation'...")
    result = run({
        "fichier": "data/test_search.txt",
        "mot": "vectalisation"
    })
    print(f"   → Occurrences: {result.get('occurrences', 0)}")
    for r in result.get("resultats", []):
        print(f"      Ligne {r['ligne']}: {r['contenu']}")
    print()
    
    # Test 2: Recherche insensible à la casse
    print("2. Recherche de 'MOSS' (insensible à la casse)...")
    result = run({
        "fichier": "data/test_search.txt",
        "mot": "moss"
    })
    print(f"   → Occurrences: {result.get('occurrences', 0)}")
    for r in result.get("resultats", []):
        print(f"      Ligne {r['ligne']}: {r['contenu']}")
    print()
    
    # Test 3: Recherche sans résultat
    print("3. Recherche de 'inexistant'...")
    result = run({
        "fichier": "data/test_search.txt",
        "mot": "inexistant"
    })
    print(f"   → Occurrences: {result.get('occurrences', 0)}")
    print()
    
    # Test 4: Recherche dans tout le dossier buffer
    print("4. Recherche dans tout le dossier buffer/...")
    result = search_in_directory("buffer", "Utilisateur")
    print(f"   → Fichiers avec résultats: {result.get('fichiers_trouves', 0)}")
    print(f"   → Total occurrences: {result.get('total_occurrences', 0)}")
    for r in result.get("resultats", [])[:3]:  # Limiter l'affichage
        print(f"      - {r['fichier']}: {r['occurrences']} occurrence(s)")
    print()
    
    # Test 5: Fichier inexistant
    print("5. Recherche dans fichier inexistant...")
    result = run({
        "fichier": "data/nexiste_pas.txt",
        "mot": "test"
    })
    print(f"   → Status: {result['status']}")
    print(f"   → Erreur: {result.get('error', 'N/A')}\n")
    
    # Nettoyage
    print("6. Nettoyage...")
    delete_file("data/test_search.txt")
    print("   → Fichier test supprimé\n")
    
    print("✅ Tests terminés!")