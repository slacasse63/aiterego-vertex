"""
read_document.py - Lecture de documents et code source pour Iris
MOSS v0.11.2

Exploite la fenêtre native Gemini 1M tokens pour lire des documents volumineux
SANS polluer la fenêtre conversationnelle tournante (~30K tokens).

Sources disponibles:
- documents: ~/Dropbox/aiterego_memory/documents/ (articles, rapports, PDF)
- code: ~/Dropbox/aiterego/app/ (code source MOSS)

Usage:
    from actions.read_document import list_documents, read_document
    
    # Lister les documents disponibles
    result = list_documents(source="documents")
    
    # Lire un document
    result = read_document(fichier="article.pdf", source="documents", question="Quel est le thème principal?")
    
    # Lire du code source
    result = read_document(fichier="main.py", source="code")

Auteurs: Serge Lacasse, Claude (session 79)
Date: 2026-01-15
"""

import os
import hashlib
import logging
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Any, Optional
import subprocess

# Imports pour lecture de fichiers
try:
    import PyPDF2
    PDF_AVAILABLE = True
except ImportError:
    PDF_AVAILABLE = False

# Import Gemini pour l'appel dédié
try:
    from google import genai
    from google.genai import types
    GEMINI_AVAILABLE = True
except ImportError:
    GEMINI_AVAILABLE = False

from dotenv import load_dotenv

# Charger les variables d'environnement
env_path = Path.home() / "Dropbox" / "aiterego" / ".env"
load_dotenv(env_path)

logger = logging.getLogger(__name__)

# === CONFIGURATION ===

# Sources disponibles
SOURCES = {
    "documents": {
        "chemin": Path("~/Dropbox/aiterego_memory/documents").expanduser(),
        "description": "Documents externes (articles, rapports, PDF)"
    },
    "code": {
        "chemin": Path("~/Dropbox/aiterego/app").expanduser(),
        "description": "Code source MOSS"
    },
    "recherche": {
        "chemin": Path("~/Dropbox/02. Recherche").expanduser(),
        "description": "Dossiers de recherche (CRSH, articles, etc.)"
    },
    "dropbox": {
        "chemin": Path("~/Dropbox").expanduser(),
        "description": "Racine Dropbox complète (tous les dossiers)"
    }
}

# Extensions supportées
EXTENSIONS_TEXTE = {".txt", ".md", ".json", ".csv", ".py", ".html", ".css", ".js", ".yaml", ".yml", ".sql", ".sh"}
EXTENSIONS_PDF = {".pdf"}
EXTENSIONS_SUPPORTEES = EXTENSIONS_TEXTE | EXTENSIONS_PDF

# Modèle Gemini pour lecture de documents (peut absorber 1M tokens)
DOCUMENT_MODEL = "gemini-3-flash-preview"  # Plus rapide et moins cher pour lecture simple

# Limite de tokens pour la synthèse (éviter réponses trop longues)
MAX_OUTPUT_TOKENS = 8192


# === FONCTIONS UTILITAIRES ===

def _get_file_hash(filepath: Path) -> str:
    """Calcule le hash MD5 d'un fichier pour détecter les changements."""
    hash_md5 = hashlib.md5()
    try:
        with open(filepath, "rb") as f:
            for chunk in iter(lambda: f.read(4096), b""):
                hash_md5.update(chunk)
        return hash_md5.hexdigest()[:12]  # 12 premiers caractères suffisent
    except Exception:
        return "unknown"


def _get_file_info(filepath: Path) -> Dict[str, Any]:
    """Retourne les métadonnées d'un fichier."""
    stat = filepath.stat()
    return {
        "nom": filepath.name,
        "chemin_relatif": str(filepath.relative_to(filepath.parent.parent)) if len(filepath.parts) > 2 else filepath.name,
        "extension": filepath.suffix.lower(),
        "taille_octets": stat.st_size,
        "taille_lisible": _format_size(stat.st_size),
        "date_modification": datetime.fromtimestamp(stat.st_mtime).isoformat(),
        "checksum": _get_file_hash(filepath)
    }


def _format_size(size_bytes: int) -> str:
    """Formate une taille en octets de manière lisible."""
    for unit in ['o', 'Ko', 'Mo', 'Go']:
        if size_bytes < 1024:
            return f"{size_bytes:.1f} {unit}"
        size_bytes /= 1024
    return f"{size_bytes:.1f} To"


def _estimate_tokens(text: str) -> int:
    """Estime le nombre de tokens (approximation: 4 chars = 1 token)."""
    return len(text) // 4


def _read_text_file(filepath: Path) -> str:
    """Lit un fichier texte avec gestion des encodages."""
    encodings = ['utf-8', 'latin-1', 'cp1252']
    for encoding in encodings:
        try:
            return filepath.read_text(encoding=encoding)
        except UnicodeDecodeError:
            continue
    raise ValueError(f"Impossible de lire {filepath} avec les encodages: {encodings}")


def _read_pdf_file(filepath: Path) -> str:
    """Lit un fichier PDF et extrait le texte."""
    if not PDF_AVAILABLE:
        raise ImportError("PyPDF2 non installé. Installez avec: pip install PyPDF2")
    
    text_parts = []
    with open(filepath, 'rb') as f:
        reader = PyPDF2.PdfReader(f)
        for page_num, page in enumerate(reader.pages, 1):
            text = page.extract_text()
            if text:
                text_parts.append(f"--- Page {page_num} ---\n{text}")
    
    return "\n\n".join(text_parts)


def _read_file_content(filepath: Path) -> str:
    """Lit le contenu d'un fichier selon son type."""
    ext = filepath.suffix.lower()
    
    if ext in EXTENSIONS_PDF:
        return _read_pdf_file(filepath)
    elif ext in EXTENSIONS_TEXTE:
        return _read_text_file(filepath)
    else:
        raise ValueError(f"Extension non supportée: {ext}")


def _convert_docx_to_markdown(filepath: Path) -> str:
    """
    Convertit un fichier .doc/.docx en Markdown via Pandoc.
    Pandoc doit être installé sur le système (brew install pandoc).
    """
    try:
        result = subprocess.run(
            ["pandoc", "-f", "docx", "-t", "markdown", str(filepath)],
            capture_output=True,
            text=True,
            timeout=120  # 2 minutes max pour gros documents
        )
        if result.returncode != 0:
            raise Exception(f"Pandoc error: {result.stderr}")
        return result.stdout
    except FileNotFoundError:
        raise Exception("Pandoc n'est pas installé. Exécuter: brew install pandoc")
    except subprocess.TimeoutExpired:
        raise Exception("Timeout: conversion Pandoc trop longue (>2min)")


def _call_gemini_dedicated(content: str, question: Optional[str], fichier: str) -> str:
    """
    Fait un appel Gemini DÉDIÉ pour analyser le document.
    
    Cette fenêtre est SÉPARÉE de la fenêtre conversationnelle d'Iris.
    Gemini peut recevoir jusqu'à 1M tokens en entrée.
    """
    if not GEMINI_AVAILABLE:
        raise ImportError("google-genai non installé")
    
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        raise ValueError("GEMINI_API_KEY non trouvée")
    
    client = genai.Client(api_key=api_key)
    
    # Construire le prompt
    if question:
        prompt = f"""Tu es Iris, l'agent conversationnel de MOSS.
Tu viens de recevoir le contenu du fichier "{fichier}" pour analyse.

CONTENU DU FICHIER:
---
{content}
---

QUESTION DE SERGE:
{question}

Réponds de manière concise et utile. Si le fichier est du code, tu peux l'analyser et suggérer des améliorations.
"""
    else:
        prompt = f"""Tu es Iris, l'agent conversationnel de MOSS.
Tu viens de recevoir le contenu du fichier "{fichier}" pour absorption.

CONTENU DU FICHIER:
---
{content}
---

Fais une synthèse du contenu:
1. Type de document/code
2. Points clés ou structure principale
3. Éléments notables ou importants

Sois concise mais informative.
"""
    
    try:
        config = types.GenerateContentConfig(
            temperature=0.3,
            max_output_tokens=MAX_OUTPUT_TOKENS
        )
        
        response = client.models.generate_content(
            model=DOCUMENT_MODEL,
            contents=prompt,
            config=config
        )
        
        # Extraire le texte de la réponse
        if hasattr(response, 'text'):
            return response.text
        elif hasattr(response, 'candidates') and response.candidates:
            candidate = response.candidates[0]
            if hasattr(candidate, 'content') and candidate.content:
                parts = candidate.content.parts
                if parts:
                    return ''.join(p.text for p in parts if hasattr(p, 'text'))
        
        return "Erreur: Réponse Gemini vide ou mal formée"
        
    except Exception as e:
        logger.error(f"Erreur appel Gemini dédié: {e}")
        return f"Erreur lors de l'analyse: {str(e)}"


# === FONCTIONS PRINCIPALES ===

def list_documents(source: str = "documents") -> Dict[str, Any]:
    """
    Liste les fichiers disponibles dans une source.
    
    Args:
        source: "documents" (défaut) ou "code"
        
    Returns:
        dict avec status, fichiers, et métadonnées
    """
    if source not in SOURCES:
        return {
            "status": "error",
            "error": f"Source inconnue: {source}. Sources disponibles: {list(SOURCES.keys())}"
        }
    
    source_info = SOURCES[source]
    base_path = source_info["chemin"]
    
    if not base_path.exists():
        # Créer le dossier documents s'il n'existe pas
        if source == "documents":
            base_path.mkdir(parents=True, exist_ok=True)
            return {
                "status": "success",
                "source": source,
                "description": source_info["description"],
                "chemin": str(base_path),
                "fichiers": [],
                "total": 0,
                "message": "Dossier créé. Aucun document pour l'instant."
            }
        return {
            "status": "error",
            "error": f"Chemin introuvable: {base_path}"
        }
    
    fichiers = []
    
    # Dossiers à exclure (évite boucles et dossiers système)
    EXCLUDED_DIRS = {'aiterego', 'aiterego_memory', '__pycache__', 'venv', '.venv', 'node_modules', 'env', '.git'}
    
    # Parcourir récursivement avec suivi des liens symboliques
    for root, dirs, files in os.walk(base_path, followlinks=True):
        # Exclure les dossiers problématiques (modification in-place)
        dirs[:] = [d for d in dirs if d not in EXCLUDED_DIRS and not d.startswith('.')]
        
        for filename in files:
            filepath = Path(root) / filename
            
            # Vérifier l'extension
            if filepath.suffix.lower() not in EXTENSIONS_SUPPORTEES:
                continue
            
            # Ignorer fichiers cachés
            if filename.startswith('.'):
                continue
            
            info = _get_file_info(filepath)
            # Chemin relatif depuis la source
            try:
                info["chemin_relatif"] = str(filepath.relative_to(base_path))
            except ValueError:
                info["chemin_relatif"] = filepath.name
            
            fichiers.append(info)
    
    # Trier par nom
    fichiers.sort(key=lambda x: x["chemin_relatif"].lower())
    
    return {
        "status": "success",
        "source": source,
        "description": source_info["description"],
        "chemin": str(base_path),
        "fichiers": fichiers,
        "total": len(fichiers),
        "extensions_supportees": list(EXTENSIONS_SUPPORTEES)
    }


def read_document(
    fichier: str,
    source: str = "documents",
    question: Optional[str] = None
) -> Dict[str, Any]:
    """
    Lit un document ou du code avec la fenêtre native 1M tokens de Gemini.
    
    Args:
        fichier: Nom du fichier à lire (peut inclure sous-dossiers: "actions/hermes_wrapper.py")
        source: "documents" (défaut) ou "code"
        question: Question spécifique sur le contenu (optionnel)
        
    Returns:
        dict avec:
            - status: "success" ou "error"
            - synthese: Synthèse/analyse de Gemini
            - trace: Métadonnées légères pour la fenêtre conversationnelle
            - error: Message d'erreur si échec
    """
    if source not in SOURCES:
        return {
            "status": "error",
            "error": f"Source inconnue: {source}. Sources disponibles: {list(SOURCES.keys())}"
        }
    
    source_info = SOURCES[source]
    base_path = source_info["chemin"]
    
    # Construire le chemin complet
    filepath = base_path / fichier
    
    if not filepath.exists():
        # Chercher le fichier récursivement si pas trouvé directement
        candidates = list(base_path.rglob(fichier))
        if len(candidates) == 1:
            filepath = candidates[0]
        elif len(candidates) > 1:
            return {
                "status": "error",
                "error": f"Plusieurs fichiers trouvés pour '{fichier}': {[str(c.relative_to(base_path)) for c in candidates[:5]]}"
            }
        else:
            return {
                "status": "error",
                "error": f"Fichier introuvable: {fichier}",
                "source": source,
                "chemin_recherche": str(base_path)
            }
    
    if not filepath.is_file():
        return {
            "status": "error",
            "error": f"'{fichier}' n'est pas un fichier"
        }
    
    # Vérifier l'extension
    ext = filepath.suffix.lower()
    
    # Extensions Word supportées via Pandoc
    WORD_EXTENSIONS = {'.doc', '.docx'}
    
    if ext not in EXTENSIONS_SUPPORTEES and ext not in WORD_EXTENSIONS:
        return {
            "status": "error",
            "error": f"Extension non supportée: {ext}. Extensions valides: {list(EXTENSIONS_SUPPORTEES)} + {list(WORD_EXTENSIONS)}"
        }
    
    # Lire le contenu
    try:
        if ext in WORD_EXTENSIONS:
            # Conversion Word → Markdown via Pandoc
            content = _convert_docx_to_markdown(filepath)
        else:
            content = _read_file_content(filepath)
    except Exception as e:
        return {
            "status": "error",
            "error": f"Erreur de lecture: {str(e)}"
        }
    
    # Estimer les tokens
    tokens_estimes = _estimate_tokens(content)
    
    # Créer la trace légère (pour la fenêtre conversationnelle)
    file_info = _get_file_info(filepath)
    trace = {
        "action": "read_document",
        "fichier": fichier,
        "source": source,
        "taille_tokens": tokens_estimes,
        "taille_lisible": file_info["taille_lisible"],
        "date_lecture": datetime.now().isoformat(),
        "checksum": file_info["checksum"],
        "converted_from": ext if ext in WORD_EXTENSIONS else None
    }
    
    # Appel Gemini dédié pour l'analyse
    try:
        synthese = _call_gemini_dedicated(content, question, fichier)
    except Exception as e:
        return {
            "status": "error",
            "error": f"Erreur analyse Gemini: {str(e)}",
            "trace": trace
        }
    
    return {
        "status": "success",
        "synthese": synthese,
        "trace": trace,
        "fichier_info": file_info
    }


def read_multiple_documents(
    fichiers: List[str],
    source: str = "code",
    question: Optional[str] = None
) -> Dict[str, Any]:
    """
    Lit plusieurs fichiers en une seule requête.
    
    Utile pour comprendre un flux complet (ex: main.py + hermes_wrapper.py + une action).
    
    Args:
        fichiers: Liste de noms de fichiers
        source: "documents" ou "code" (défaut)
        question: Question sur l'ensemble des fichiers
        
    Returns:
        dict avec synthèse combinée et traces individuelles
    """
    if not fichiers:
        return {
            "status": "error",
            "error": "Liste de fichiers vide"
        }
    
    if len(fichiers) > 10:
        return {
            "status": "error",
            "error": f"Maximum 10 fichiers à la fois (reçu: {len(fichiers)})"
        }
    
    source_info = SOURCES.get(source)
    if not source_info:
        return {
            "status": "error",
            "error": f"Source inconnue: {source}"
        }
    
    base_path = source_info["chemin"]
    
    # Lire tous les fichiers
    contenus = []
    traces = []
    erreurs = []
    
    for fichier in fichiers:
        filepath = base_path / fichier
        
        # Recherche récursive si nécessaire
        if not filepath.exists():
            candidates = list(base_path.rglob(fichier))
            if len(candidates) == 1:
                filepath = candidates[0]
            else:
                erreurs.append(f"'{fichier}' non trouvé")
                continue
        
        try:
            content = _read_file_content(filepath)
            contenus.append(f"=== FICHIER: {fichier} ===\n{content}")
            
            file_info = _get_file_info(filepath)
            traces.append({
                "fichier": fichier,
                "taille_tokens": _estimate_tokens(content),
                "checksum": file_info["checksum"]
            })
        except Exception as e:
            erreurs.append(f"'{fichier}': {str(e)}")
    
    if not contenus:
        return {
            "status": "error",
            "error": "Aucun fichier n'a pu être lu",
            "erreurs": erreurs
        }
    
    # Combiner les contenus
    contenu_combine = "\n\n".join(contenus)
    tokens_total = _estimate_tokens(contenu_combine)
    
    # Appel Gemini
    try:
        synthese = _call_gemini_dedicated(contenu_combine, question, ", ".join(fichiers))
    except Exception as e:
        return {
            "status": "error",
            "error": f"Erreur analyse: {str(e)}",
            "traces": traces
        }
    
    return {
        "status": "success",
        "synthese": synthese,
        "fichiers_lus": len(traces),
        "tokens_total": tokens_total,
        "traces": traces,
        "erreurs": erreurs if erreurs else None
    }


# === TEST ===
if __name__ == "__main__":
    print("=" * 60)
    print("READ_DOCUMENT - Test")
    print("=" * 60)
    
    # Test 1: Lister les documents
    print("\n1. Test list_documents('documents')...")
    result = list_documents("documents")
    print(f"   Status: {result['status']}")
    print(f"   Total: {result.get('total', 0)} fichiers")
    
    # Test 2: Lister le code
    print("\n2. Test list_documents('code')...")
    result = list_documents("code")
    print(f"   Status: {result['status']}")
    print(f"   Total: {result.get('total', 0)} fichiers")
    if result.get('fichiers'):
        print(f"   Exemples: {[f['chemin_relatif'] for f in result['fichiers'][:5]]}")
    
    # Test 3: Lire un fichier de code
    print("\n3. Test read_document('config.py', source='code')...")
    result = read_document("config.py", source="code", question="Quels sont les chemins configurés?")
    print(f"   Status: {result['status']}")
    if result['status'] == 'success':
        print(f"   Tokens: {result['trace']['taille_tokens']}")
        print(f"   Synthèse: {result['synthese'][:200]}...")
    else:
        print(f"   Erreur: {result.get('error')}")
    
    print("\n" + "=" * 60)
    print("Tests terminés!")
