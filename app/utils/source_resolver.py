"""
source_resolver.py - Résolution d'URIs vers chemins locaux
MOSS v0.11.5

Permet d'abstraire l'accès aux fichiers via des URIs canoniques,
assurant la portabilité entre Mac Studio Ultra et MacBook Pro.

URIs supportées (validées Mission 002 - 2026-01-13):
- dropbox://chemin/vers/fichier → ~/Dropbox/chemin/vers/fichier
- gdrive://chemin/vers/fichier → ~/Google Drive/chemin/vers/fichier (ou téléchargement temp)
- file:///chemin/absolu → /chemin/absolu
- file://relatif → résolu depuis DROPBOX_ROOT

Usage:
    from utils.source_resolver import resolve_source, build_uri, SourceType
    
    # Résoudre une URI vers un chemin local
    path = resolve_source("dropbox://aiterego_memory/documents/rapport.pdf")
    
    # Construire une URI depuis un chemin
    uri = build_uri("/Users/serge/Dropbox/aiterego/main.py")
    # → "dropbox://aiterego/main.py"

Auteurs: Serge Lacasse, Claude (session 80)
Date: 2026-01-16
"""

import os
import logging
import hashlib
import tempfile
from pathlib import Path
from typing import Optional, Tuple, Literal
from enum import Enum
from dataclasses import dataclass

logger = logging.getLogger(__name__)

# === CONFIGURATION ===

# Racines configurables (s'adaptent à la machine)
DROPBOX_ROOT = Path("~/Dropbox").expanduser().resolve()
GDRIVE_ROOT = Path("~/Google Drive").expanduser().resolve()

# Alternative Google Drive (certaines installations)
GDRIVE_ROOT_ALT = Path("~/Library/CloudStorage/GoogleDrive-sergiolacasse@gmail.com/My Drive").expanduser()

# Dossier pour fichiers temporaires téléchargés
TEMP_CACHE_DIR = Path(tempfile.gettempdir()) / "moss_source_cache"


class SourceType(str, Enum):
    """Types de sources supportés."""
    DROPBOX = "dropbox"
    GDRIVE = "gdrive"
    LOCAL = "local"
    URL = "url"
    UNKNOWN = "unknown"


@dataclass
class ResolvedSource:
    """Résultat de la résolution d'une URI."""
    uri: str                      # URI originale
    source_type: SourceType       # Type de source
    local_path: Optional[Path]    # Chemin local résolu (None si non trouvé)
    exists: bool                  # Le fichier existe-t-il ?
    is_cached: bool               # Est-ce un fichier temporaire/cache ?
    error: Optional[str]          # Message d'erreur si échec


def _detect_gdrive_root() -> Optional[Path]:
    """
    Détecte la racine Google Drive selon l'installation.
    Retourne None si Google Drive n'est pas installé.
    """
    # Méthode 1: ~/Google Drive (ancienne installation)
    if GDRIVE_ROOT.exists():
        return GDRIVE_ROOT
    
    # Méthode 2: CloudStorage (nouvelle installation macOS)
    if GDRIVE_ROOT_ALT.exists():
        return GDRIVE_ROOT_ALT
    
    # Méthode 3: Chercher dans CloudStorage
    cloud_storage = Path("~/Library/CloudStorage").expanduser()
    if cloud_storage.exists():
        for folder in cloud_storage.iterdir():
            if folder.name.startswith("GoogleDrive"):
                my_drive = folder / "My Drive"
                if my_drive.exists():
                    return my_drive
    
    return None


def _parse_uri(uri: str) -> Tuple[SourceType, str]:
    """
    Parse une URI et retourne (type, chemin_relatif).
    
    Exemples:
        "dropbox://aiterego/main.py" → (DROPBOX, "aiterego/main.py")
        "gdrive://AIter Ego/doc.pdf" → (GDRIVE, "AIter Ego/doc.pdf")
        "file:///absolute/path" → (LOCAL, "/absolute/path")
        "/some/path" → (LOCAL, "/some/path")
    """
    uri = uri.strip()
    
    if uri.startswith("dropbox://"):
        return SourceType.DROPBOX, uri[10:]
    
    elif uri.startswith("gdrive://"):
        return SourceType.GDRIVE, uri[9:]
    
    elif uri.startswith("file://"):
        path = uri[7:]
        # file:///absolute vs file://relative
        if path.startswith("/"):
            return SourceType.LOCAL, path
        else:
            return SourceType.LOCAL, path
    
    elif uri.startswith("http://") or uri.startswith("https://"):
        return SourceType.URL, uri
    
    elif uri.startswith("/") or uri.startswith("~"):
        # Chemin absolu direct
        return SourceType.LOCAL, uri
    
    else:
        # Chemin relatif - on assume Dropbox par défaut
        return SourceType.DROPBOX, uri


def resolve_source(uri: str) -> ResolvedSource:
    """
    Résout une URI en chemin local accessible.
    
    Args:
        uri: URI à résoudre (dropbox://, gdrive://, file://, ou chemin direct)
        
    Returns:
        ResolvedSource avec le chemin local ou une erreur
        
    Examples:
        >>> result = resolve_source("dropbox://aiterego_memory/documents/rapport.pdf")
        >>> if result.exists:
        ...     content = result.local_path.read_text()
    """
    source_type, relative_path = _parse_uri(uri)
    
    # === DROPBOX ===
    if source_type == SourceType.DROPBOX:
        if not DROPBOX_ROOT.exists():
            return ResolvedSource(
                uri=uri,
                source_type=source_type,
                local_path=None,
                exists=False,
                is_cached=False,
                error="Dropbox non trouvé. Vérifier que Dropbox est installé."
            )
        
        local_path = DROPBOX_ROOT / relative_path
        
        # Suivre les liens symboliques
        try:
            local_path = local_path.resolve()
        except (OSError, RuntimeError) as e:
            return ResolvedSource(
                uri=uri,
                source_type=source_type,
                local_path=local_path,
                exists=False,
                is_cached=False,
                error=f"Erreur résolution symlink: {e}"
            )
        
        return ResolvedSource(
            uri=uri,
            source_type=source_type,
            local_path=local_path,
            exists=local_path.exists(),
            is_cached=False,
            error=None if local_path.exists() else f"Fichier non trouvé: {local_path}"
        )
    
    # === GOOGLE DRIVE ===
    elif source_type == SourceType.GDRIVE:
        gdrive_root = _detect_gdrive_root()
        
        if not gdrive_root:
            return ResolvedSource(
                uri=uri,
                source_type=source_type,
                local_path=None,
                exists=False,
                is_cached=False,
                error="Google Drive non trouvé. Installer Google Drive for Desktop."
            )
        
        local_path = gdrive_root / relative_path
        
        # Suivre les liens symboliques
        try:
            local_path = local_path.resolve()
        except (OSError, RuntimeError) as e:
            return ResolvedSource(
                uri=uri,
                source_type=source_type,
                local_path=local_path,
                exists=False,
                is_cached=False,
                error=f"Erreur résolution: {e}"
            )
        
        return ResolvedSource(
            uri=uri,
            source_type=source_type,
            local_path=local_path,
            exists=local_path.exists(),
            is_cached=False,
            error=None if local_path.exists() else f"Fichier non trouvé: {local_path}"
        )
    
    # === LOCAL ===
    elif source_type == SourceType.LOCAL:
        local_path = Path(relative_path).expanduser().resolve()
        
        return ResolvedSource(
            uri=uri,
            source_type=source_type,
            local_path=local_path,
            exists=local_path.exists(),
            is_cached=False,
            error=None if local_path.exists() else f"Fichier non trouvé: {local_path}"
        )
    
    # === URL (non implémenté pour l'instant) ===
    elif source_type == SourceType.URL:
        return ResolvedSource(
            uri=uri,
            source_type=source_type,
            local_path=None,
            exists=False,
            is_cached=False,
            error="Téléchargement URL non encore implémenté"
        )
    
    # === UNKNOWN ===
    else:
        return ResolvedSource(
            uri=uri,
            source_type=SourceType.UNKNOWN,
            local_path=None,
            exists=False,
            is_cached=False,
            error=f"Type de source non reconnu: {uri}"
        )


def build_uri(local_path: str | Path) -> str:
    """
    Construit une URI canonique depuis un chemin local.
    
    Args:
        local_path: Chemin local absolu ou relatif
        
    Returns:
        URI canonique (dropbox://, gdrive://, ou file://)
        
    Examples:
        >>> build_uri("/Users/serge/Dropbox/aiterego/main.py")
        'dropbox://aiterego/main.py'
        
        >>> build_uri("~/Google Drive/AIter Ego/doc.pdf")
        'gdrive://AIter Ego/doc.pdf'
    """
    path = Path(local_path).expanduser().resolve()
    path_str = str(path)
    
    # Vérifier si c'est dans Dropbox
    dropbox_str = str(DROPBOX_ROOT)
    if path_str.startswith(dropbox_str):
        relative = path_str[len(dropbox_str):].lstrip("/")
        return f"dropbox://{relative}"
    
    # Vérifier si c'est dans Google Drive
    gdrive_root = _detect_gdrive_root()
    if gdrive_root:
        gdrive_str = str(gdrive_root)
        if path_str.startswith(gdrive_str):
            relative = path_str[len(gdrive_str):].lstrip("/")
            return f"gdrive://{relative}"
    
    # Sinon, URI locale
    return f"file://{path_str}"


def get_source_type(uri_or_path: str) -> SourceType:
    """
    Retourne le type de source sans résoudre complètement.
    
    Utile pour des décisions rapides sans I/O disque.
    """
    source_type, _ = _parse_uri(uri_or_path)
    return source_type


def normalize_uri(uri: str) -> str:
    """
    Normalise une URI (résout et reconstruit).
    
    Utile pour avoir des URIs cohérentes dans la base de données.
    """
    result = resolve_source(uri)
    if result.local_path and result.exists:
        return build_uri(result.local_path)
    return uri  # Retourner l'original si non résolu


def list_sources() -> dict:
    """
    Liste les sources disponibles et leur état.
    
    Utile pour diagnostiquer la configuration.
    """
    gdrive_root = _detect_gdrive_root()
    
    return {
        "dropbox": {
            "available": DROPBOX_ROOT.exists(),
            "path": str(DROPBOX_ROOT) if DROPBOX_ROOT.exists() else None
        },
        "gdrive": {
            "available": gdrive_root is not None,
            "path": str(gdrive_root) if gdrive_root else None
        },
        "temp_cache": {
            "path": str(TEMP_CACHE_DIR),
            "exists": TEMP_CACHE_DIR.exists()
        }
    }


# === TEST ===
if __name__ == "__main__":
    print("=" * 60)
    print("SOURCE_RESOLVER v0.11.5 - Test")
    print("=" * 60)
    
    # Test 1: Lister les sources
    print("\n1. Sources disponibles:")
    sources = list_sources()
    for name, info in sources.items():
        status = "✅" if info.get("available", info.get("exists", False)) else "❌"
        print(f"   {status} {name}: {info.get('path', 'N/A')}")
    
    # Test 2: Résolution Dropbox
    print("\n2. Test résolution Dropbox:")
    test_uri = "dropbox://aiterego/app/main.py"
    result = resolve_source(test_uri)
    print(f"   URI: {test_uri}")
    print(f"   Type: {result.source_type}")
    print(f"   Path: {result.local_path}")
    print(f"   Exists: {result.exists}")
    
    # Test 3: Résolution Google Drive
    print("\n3. Test résolution Google Drive:")
    test_uri = "gdrive://AIter Ego/Iris/blackboard.md"
    result = resolve_source(test_uri)
    print(f"   URI: {test_uri}")
    print(f"   Type: {result.source_type}")
    print(f"   Path: {result.local_path}")
    print(f"   Exists: {result.exists}")
    if result.error:
        print(f"   Error: {result.error}")
    
    # Test 4: Construction d'URI
    print("\n4. Test construction URI:")
    if DROPBOX_ROOT.exists():
        test_path = DROPBOX_ROOT / "aiterego" / "app" / "config.py"
        uri = build_uri(test_path)
        print(f"   Path: {test_path}")
        print(f"   URI: {uri}")
    
    # Test 5: Chemin direct
    print("\n5. Test chemin direct:")
    test_path = "/tmp/test.txt"
    result = resolve_source(test_path)
    print(f"   Input: {test_path}")
    print(f"   Type: {result.source_type}")
    print(f"   URI construite: {build_uri(test_path)}")
    
    print("\n" + "=" * 60)
    print("Tests terminés!")
