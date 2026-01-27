"""
common_header.py - Header commun pour toutes les actions AIter Ego
Version unifiée qui fonctionne en local ET sur Azure.

Usage dans une action:
    from actions_config.common_header import *
    
    def run(params):
        contenu = read_file("data/mon_fichier.txt")
        result = write_file("data/output.txt", contenu)
        return {"status": "success", "timestamp": get_timestamp()}
"""

import os
from datetime import datetime, timezone

# === IMPORT DES FONCTIONS DE STOCKAGE ===
from utils.storage import (
    read_file,
    write_file,
    append_file,
    delete_file,
    list_files,
    file_exists,
    create_directory,
    STORAGE_MODE
)

# === CONFIGURATION ===
# Mode de stockage (hérité de storage.py)
# "local" = fichiers sur disque
# "azure" = Azure Files/Blob Storage

# === TIMESTAMP ===
def get_timestamp() -> str:
    """
    Retourne un horodatage UTC au format ISO 8601 Zulu.
    Ex: 2025-12-10T19:45:30.083Z
    """
    return datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%S.%f')[:-3] + 'Z'


# === CHEMINS (pour compatibilité avec le code Azure existant) ===
# En mode local, ces variables ne sont pas utilisées mais restent définies
# pour éviter les erreurs d'import dans le code Azure existant

# Azure Files (legacy)
share_client = None

# Azure Blob (legacy)  
container_client = None

# User ID (en local: pas de multi-utilisateur)
USER_ID = os.environ.get("USER_ID", "").strip()


def resolve_path(path: str) -> str:
    """
    Résout un chemin de fichier.
    En local: retourne le chemin tel quel (storage.py gère la résolution)
    En Azure: préfixe avec USER_ID si nécessaire
    
    Args:
        path: Chemin relatif du fichier
    
    Returns:
        Chemin résolu
    """
    path = path.strip().lstrip("/")
    
    if STORAGE_MODE == "local":
        # En local, pas de préfixe utilisateur
        return path
    
    else:
        # En Azure, préfixer avec USER_ID si défini et pas déjà présent
        if USER_ID and not path.startswith(f"{USER_ID}/") and not path.startswith(f"users/{USER_ID}/"):
            return f"{USER_ID}/{path}"
        return path


# === HELPERS ADDITIONNELS ===

def safe_read(path: str, default: str = "") -> str:
    """
    Lecture sécurisée - retourne default si le fichier n'existe pas.
    
    Args:
        path: Chemin du fichier
        default: Valeur par défaut si fichier inexistant
    
    Returns:
        Contenu du fichier ou default
    """
    try:
        return read_file(resolve_path(path))
    except FileNotFoundError:
        return default
    except Exception as e:
        return default


def safe_write(path: str, content: str) -> dict:
    """
    Écriture sécurisée avec gestion d'erreur.
    
    Args:
        path: Chemin du fichier
        content: Contenu à écrire
    
    Returns:
        dict avec status, path, timestamp (ou error)
    """
    try:
        return write_file(resolve_path(path), content)
    except Exception as e:
        return {
            "status": "error",
            "error": str(e),
            "path": path,
            "timestamp": get_timestamp()
        }


# === EXPORTS ===
# Tout ce qui est importé avec "from common_header import *"
__all__ = [
    # Fonctions de stockage
    "read_file",
    "write_file", 
    "append_file",
    "delete_file",
    "list_files",
    "file_exists",
    "create_directory",
    # Helpers
    "get_timestamp",
    "resolve_path",
    "safe_read",
    "safe_write",
    # Config
    "STORAGE_MODE",
    "USER_ID",
    # Legacy Azure (pour compatibilité)
    "share_client",
    "container_client",
]


# === TEST ===
if __name__ == "__main__":
    print(f"=== Test common_header.py ===")
    print(f"Mode stockage: {STORAGE_MODE}")
    print(f"User ID: '{USER_ID}' (vide = normal en local)")
    print(f"Timestamp: {get_timestamp()}")
    print()
    
    # Test resolve_path
    print("Test resolve_path:")
    print(f"  'data/test.txt' → '{resolve_path('data/test.txt')}'")
    print(f"  '/buffer/chunk.txt' → '{resolve_path('/buffer/chunk.txt')}'")
    print()
    
    # Test safe_read
    print("Test safe_read:")
    print(f"  Fichier inexistant → '{safe_read('inexistant.txt', 'DEFAUT')}'")
    print()
    
    print("✅ common_header.py prêt!")