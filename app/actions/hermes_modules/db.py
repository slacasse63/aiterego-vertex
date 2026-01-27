"""
hermes_modules/db.py - Connexion SQLite et normalisation

Contient la fonction magique _normalize_search injectée dans SQLite.
"""

import sqlite3
import unicodedata
import json

from .config import DB_PATH


def _normalize_search(text: str) -> str:
    """
    Fonction injectée dans SQLite pour normaliser accents et JSON.
    Transforme : '["Christian Gagn\\u00e9"]' -> 'christian gagne'
    Transforme : 'Été' -> 'ete'
    """
    if not text:
        return ""
    
    # 1. Décodage JSON (si c'est une liste stockée en string avec caractères échappés)
    # Ex: '["Christian Gagn\\u00e9"]'
    if isinstance(text, str) and text.strip().startswith("[") and ("\\" in text or "]" in text):
        try:
            decoded = json.loads(text)
            if isinstance(decoded, list):
                # On joint tous les éléments de la liste (ex: plusieurs auteurs)
                text = " ".join(str(x) for x in decoded)
        except:
            pass  # Ce n'était pas du JSON valide, on continue avec le texte brut

    # 2. Nettoyage Unicode (NFD) pour enlever les accents
    # NFD sépare le 'é' en 'e' + 'accent', puis on filtre l'accent (catégorie Mn)
    text = unicodedata.normalize('NFD', text)
    text = "".join(c for c in text if unicodedata.category(c) != 'Mn')
    
    return text.lower()


def _get_connection() -> sqlite3.Connection:
    """Crée une connexion SQLite avec injection de la fonction normalize_search."""
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    
    # === INJECTION CRITIQUE ===
    # Apprend à SQLite comment normaliser JSON et accents
    conn.create_function("normalize_search", 1, _normalize_search)
    
    return conn