"""
storage.py - Abstraction de stockage pour AIter Ego
Permet de switcher entre stockage local (fichiers) et Azure (Blob/Files)
via la variable d'environnement STORAGE_MODE.

Usage:
    from utils.storage import read_file, write_file, list_files, delete_file
    
    contenu = read_file("data/contexte.txt")
    write_file("data/test.txt", "Hello world")
    fichiers = list_files("buffer/")
    delete_file("data/old.txt")
"""

import os
import logging
from pathlib import Path
from typing import List, Optional
from datetime import datetime, timezone

# === CONFIGURATION ===
STORAGE_MODE = os.environ.get("STORAGE_MODE", "local")  # "local" ou "azure"

# Chemins locaux (runtime dans app/)
LOCAL_BASE_DIR = Path(__file__).parent.parent  # Remonte de utils/ à app/
LOCAL_DATA_DIR = LOCAL_BASE_DIR / "data"
LOCAL_BUFFER_DIR = LOCAL_BASE_DIR / "buffer"

# Azure (chargé seulement si nécessaire)
_azure_clients = {}

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


# === HELPERS ===
def get_timestamp() -> str:
    """Retourne timestamp UTC au format ISO avec 'Z'."""
    return datetime.now(timezone.utc).isoformat(timespec='milliseconds') + 'Z'


def _resolve_local_path(path: str) -> Path:
    """
    Résout un chemin relatif vers un chemin absolu local.
    Ex: "data/contexte.txt" → /Users/.../mistral/app/data/contexte.txt
    """
    path = path.strip().lstrip("/")
    return LOCAL_BASE_DIR / path


def _get_azure_clients():
    """Initialise les clients Azure (lazy loading)."""
    global _azure_clients
    
    if not _azure_clients:
        try:
            from azure.storage.fileshare import ShareServiceClient
            from azure.storage.blob import BlobServiceClient
            
            conn_string = os.environ.get("AZURE_CONNECTION_STRING", "")
            share_name = os.environ.get("AZURE_SHARE_NAME", "")
            container_name = os.environ.get("AZURE_CONTAINER_NAME", "")
            
            if conn_string:
                if share_name:
                    file_service = ShareServiceClient.from_connection_string(conn_string)
                    _azure_clients["share"] = file_service.get_share_client(share_name)
                
                if container_name:
                    blob_service = BlobServiceClient.from_connection_string(conn_string)
                    _azure_clients["container"] = blob_service.get_container_client(container_name)
                    
        except ImportError:
            logger.warning("Azure SDK non installé - mode local uniquement")
        except Exception as e:
            logger.error(f"Erreur initialisation Azure: {e}")
    
    return _azure_clients


# === FONCTIONS PRINCIPALES ===

def read_file(path: str, storage_type: str = "file") -> str:
    """
    Lit le contenu d'un fichier.
    
    Args:
        path: Chemin relatif du fichier (ex: "data/contexte.txt")
        storage_type: "file" (Azure Files) ou "blob" (Azure Blob) - ignoré en local
    
    Returns:
        Contenu du fichier (string)
    
    Raises:
        FileNotFoundError: Si le fichier n'existe pas
        Exception: Autres erreurs de lecture
    """
    if STORAGE_MODE == "local":
        full_path = _resolve_local_path(path)
        logger.debug(f"[LOCAL] Lecture: {full_path}")
        
        if not full_path.exists():
            raise FileNotFoundError(f"Fichier non trouvé: {path}")
        
        return full_path.read_text(encoding='utf-8')
    
    else:  # Azure
        clients = _get_azure_clients()
        path = path.strip().lstrip("/")
        logger.debug(f"[AZURE] Lecture: {path}")
        
        if storage_type == "file" and "share" in clients:
            file_client = clients["share"].get_file_client(path)
            return file_client.download_file().readall().decode("utf-8")
        
        elif storage_type == "blob" and "container" in clients:
            blob_client = clients["container"].get_blob_client(blob=path)
            return blob_client.download_blob().readall().decode("utf-8")
        
        else:
            raise ValueError(f"Client Azure non disponible pour storage_type={storage_type}")


def write_file(path: str, content: str, storage_type: str = "file") -> dict:
    """
    Écrit (ou réécrit) un fichier.
    
    Args:
        path: Chemin relatif du fichier
        content: Contenu à écrire
        storage_type: "file" ou "blob" - ignoré en local
    
    Returns:
        dict avec status et timestamp
    """
    timestamp = get_timestamp()
    
    if STORAGE_MODE == "local":
        full_path = _resolve_local_path(path)
        logger.debug(f"[LOCAL] Écriture: {full_path}")
        
        # Créer le dossier parent si nécessaire
        full_path.parent.mkdir(parents=True, exist_ok=True)
        full_path.write_text(content, encoding='utf-8')
        
        return {
            "status": "success",
            "path": str(full_path),
            "timestamp": timestamp
        }
    
    else:  # Azure
        clients = _get_azure_clients()
        path = path.strip().lstrip("/")
        logger.debug(f"[AZURE] Écriture: {path}")
        
        if storage_type == "file" and "share" in clients:
            file_client = clients["share"].get_file_client(path)
            file_client.upload_file(content, overwrite=True)
        
        elif storage_type == "blob" and "container" in clients:
            blob_client = clients["container"].get_blob_client(blob=path)
            blob_client.upload_blob(content, overwrite=True)
        
        else:
            raise ValueError(f"Client Azure non disponible pour storage_type={storage_type}")
        
        return {
            "status": "success",
            "path": path,
            "timestamp": timestamp
        }


def append_file(path: str, content: str, storage_type: str = "file") -> dict:
    """
    Ajoute du contenu à la fin d'un fichier existant.
    Crée le fichier s'il n'existe pas.
    
    Args:
        path: Chemin relatif du fichier
        content: Contenu à ajouter
        storage_type: "file" ou "blob" - ignoré en local
    
    Returns:
        dict avec status et timestamp
    """
    try:
        existing = read_file(path, storage_type)
    except FileNotFoundError:
        existing = ""
    
    return write_file(path, existing + content, storage_type)


def delete_file(path: str, storage_type: str = "file") -> dict:
    """
    Supprime un fichier.
    
    Args:
        path: Chemin relatif du fichier
        storage_type: "file" ou "blob" - ignoré en local
    
    Returns:
        dict avec status et timestamp
    """
    timestamp = get_timestamp()
    
    if STORAGE_MODE == "local":
        full_path = _resolve_local_path(path)
        logger.debug(f"[LOCAL] Suppression: {full_path}")
        
        if not full_path.exists():
            return {
                "status": "not_found",
                "path": str(full_path),
                "timestamp": timestamp
            }
        
        full_path.unlink()
        
        return {
            "status": "success",
            "path": str(full_path),
            "timestamp": timestamp
        }
    
    else:  # Azure
        clients = _get_azure_clients()
        path = path.strip().lstrip("/")
        logger.debug(f"[AZURE] Suppression: {path}")
        
        if storage_type == "file" and "share" in clients:
            file_client = clients["share"].get_file_client(path)
            file_client.delete_file()
        
        elif storage_type == "blob" and "container" in clients:
            blob_client = clients["container"].get_blob_client(blob=path)
            blob_client.delete_blob()
        
        else:
            raise ValueError(f"Client Azure non disponible pour storage_type={storage_type}")
        
        return {
            "status": "success",
            "path": path,
            "timestamp": timestamp
        }


def list_files(directory: str, storage_type: str = "file") -> List[str]:
    """
    Liste les fichiers dans un dossier.
    
    Args:
        directory: Chemin relatif du dossier (ex: "buffer/")
        storage_type: "file" ou "blob" - ignoré en local
    
    Returns:
        Liste des noms de fichiers
    """
    if STORAGE_MODE == "local":
        full_path = _resolve_local_path(directory)
        logger.debug(f"[LOCAL] Liste: {full_path}")
        
        if not full_path.exists():
            return []
        
        return [f.name for f in full_path.iterdir() if f.is_file()]
    
    else:  # Azure
        clients = _get_azure_clients()
        directory = directory.strip().lstrip("/").rstrip("/") + "/"
        logger.debug(f"[AZURE] Liste: {directory}")
        
        files = []
        
        if storage_type == "file" and "share" in clients:
            dir_client = clients["share"].get_directory_client(directory)
            for item in dir_client.list_directories_and_files():
                if not item.get("is_directory", False):
                    files.append(item["name"])
        
        elif storage_type == "blob" and "container" in clients:
            for blob in clients["container"].list_blobs(name_starts_with=directory):
                # Extraire juste le nom du fichier (sans le chemin)
                name = blob.name[len(directory):]
                if name and "/" not in name:  # Fichier direct, pas sous-dossier
                    files.append(name)
        
        return files


def file_exists(path: str, storage_type: str = "file") -> bool:
    """
    Vérifie si un fichier existe.
    
    Args:
        path: Chemin relatif du fichier
        storage_type: "file" ou "blob" - ignoré en local
    
    Returns:
        True si le fichier existe
    """
    if STORAGE_MODE == "local":
        full_path = _resolve_local_path(path)
        return full_path.exists() and full_path.is_file()
    
    else:  # Azure
        try:
            read_file(path, storage_type)
            return True
        except:
            return False


def create_directory(directory: str, storage_type: str = "file") -> dict:
    """
    Crée un dossier (et ses parents si nécessaire).
    
    Args:
        directory: Chemin relatif du dossier
        storage_type: "file" ou "blob" - ignoré en local
    
    Returns:
        dict avec status et timestamp
    """
    timestamp = get_timestamp()
    
    if STORAGE_MODE == "local":
        full_path = _resolve_local_path(directory)
        logger.debug(f"[LOCAL] Création dossier: {full_path}")
        
        full_path.mkdir(parents=True, exist_ok=True)
        
        return {
            "status": "success",
            "path": str(full_path),
            "timestamp": timestamp
        }
    
    else:  # Azure
        clients = _get_azure_clients()
        directory = directory.strip().lstrip("/").rstrip("/")
        logger.debug(f"[AZURE] Création dossier: {directory}")
        
        if storage_type == "file" and "share" in clients:
            # Azure Files: créer le dossier explicitement
            dir_client = clients["share"].get_directory_client(directory)
            dir_client.create_directory()
        
        elif storage_type == "blob" and "container" in clients:
            # Azure Blob: les dossiers n'existent pas vraiment, on crée un placeholder
            blob_client = clients["container"].get_blob_client(blob=f"{directory}/.placeholder")
            blob_client.upload_blob("", overwrite=True)
        
        return {
            "status": "success",
            "path": directory,
            "timestamp": timestamp
        }


# === TEST ===
if __name__ == "__main__":
    print(f"=== Test storage.py (mode: {STORAGE_MODE}) ===\n")
    
    # Test écriture
    print("1. Test write_file...")
    result = write_file("data/test_storage.txt", "Hello from storage.py!")
    print(f"   → {result}\n")
    
    # Test lecture
    print("2. Test read_file...")
    content = read_file("data/test_storage.txt")
    print(f"   → Contenu: {content}\n")
    
    # Test append
    print("3. Test append_file...")
    result = append_file("data/test_storage.txt", "\nLigne ajoutée!")
    content = read_file("data/test_storage.txt")
    print(f"   → Contenu après append: {content}\n")
    
    # Test list
    print("4. Test list_files...")
    files = list_files("data/")
    print(f"   → Fichiers dans data/: {files}\n")
    
    # Test exists
    print("5. Test file_exists...")
    print(f"   → test_storage.txt existe: {file_exists('data/test_storage.txt')}")
    print(f"   → inexistant.txt existe: {file_exists('data/inexistant.txt')}\n")
    
    # Test delete
    print("6. Test delete_file...")
    result = delete_file("data/test_storage.txt")
    print(f"   → {result}")
    print(f"   → Existe encore: {file_exists('data/test_storage.txt')}\n")
    
    print("✅ Tous les tests passés!")