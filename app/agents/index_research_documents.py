#!/usr/bin/env python3
"""
index_research_documents.py v2
MOSS - Indexation des documents de recherche avec Gemini 2.5 Flash Lite

Version 2 : Accès direct à Dropbox via API (plus de problème "online-only")

Architecture :
- Dropbox API → lecture directe des fichiers cloud
- Gemini 2.5 Flash Lite → résumés, mots-clés, entités, langue
- text-embedding-004 → vecteurs denses 768D
- Stockage dans file_index.db (table research_analysis)

Usage :
    # Via Dropbox API (recommandé)
    python index_research_documents.py --folder "/02. Recherche" --source dropbox --limit 10
    
    # Via système de fichiers local (ancien mode)
    python index_research_documents.py --folder "~/Dropbox/02. Recherche" --source local --limit 10
    
    # Reprendre après interruption
    python index_research_documents.py --resume --source dropbox

Auteur : Claude (L'Architecte) pour le Conseil des Agents AIter Ego
Date : 2026-01-27
Version : 2.0 - Accès Dropbox API
"""

import os
import sys
import json
import sqlite3
import hashlib
import logging
import argparse
import time
import tempfile
import io
from pathlib import Path
from datetime import datetime
from typing import Optional, Dict, Any, List, Tuple

# === CONFIGURATION ===
DEFAULT_RESEARCH_FOLDER = "/02. Recherche"  # Chemin Dropbox (pas local)
FILE_INDEX_DB = Path.home() / "Dropbox" / "aiterego_memory" / "file_index.db"
CHECKPOINT_FILE = Path.home() / "Dropbox" / "aiterego_memory" / "logs" / "indexation_checkpoint.json"
LOG_FILE = Path.home() / "Dropbox" / "aiterego_memory" / "logs" / "indexation_research.log"

# Extensions supportées
SUPPORTED_EXTENSIONS = {
    '.txt', '.md', '.markdown',
    '.pdf',
    '.docx', '.doc',
    '.rtf',
    '.html', '.htm',
    '.tex',
    '.json', '.xml'
}

# Rate limiting
REQUESTS_PER_MINUTE = 60
DELAY_BETWEEN_REQUESTS = 1.0
MAX_RETRIES = 3
RETRY_DELAY = 30

# Chunking
MAX_CHUNK_SIZE = 30000
OVERLAP_SIZE = 500

# === LOGGING ===
def setup_logging():
    """Configure le logging avec fichier et console."""
    LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s [%(levelname)s] %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S',
        handlers=[
            logging.FileHandler(LOG_FILE, encoding='utf-8'),
            logging.StreamHandler(sys.stdout)
        ]
    )
    return logging.getLogger(__name__)

logger = setup_logging()

# === DROPBOX API ===
class DropboxClient:
    """Client Dropbox avec gestion du refresh token."""
    
    def __init__(self):
        self.app_key = os.environ.get('DROPBOX_APP_KEY')
        self.app_secret = os.environ.get('DROPBOX_APP_SECRET')
        self.refresh_token = os.environ.get('DROPBOX_REFRESH_TOKEN')
        self.access_token = None
        self.dbx = None
        
        if not all([self.app_key, self.app_secret, self.refresh_token]):
            raise ValueError(
                "Variables Dropbox manquantes. Définissez DROPBOX_APP_KEY, "
                "DROPBOX_APP_SECRET et DROPBOX_REFRESH_TOKEN dans l'environnement."
            )
        
        self._init_client()
    
    def _init_client(self):
        """Initialise le client Dropbox avec refresh token."""
        try:
            import dropbox
            from dropbox import DropboxOAuth2FlowNoRedirect
            
            self.dbx = dropbox.Dropbox(
                app_key=self.app_key,
                app_secret=self.app_secret,
                oauth2_refresh_token=self.refresh_token
            )
            # Test de connexion
            account = self.dbx.users_get_current_account()
            logger.info(f"Connecté à Dropbox: {account.email}")
            
        except ImportError:
            logger.error("Installez dropbox: pip install dropbox")
            sys.exit(1)
        except Exception as e:
            logger.error(f"Erreur connexion Dropbox: {e}")
            sys.exit(1)
    
    def list_files(self, folder_path: str, extensions: set) -> List[Dict[str, Any]]:
        """Liste récursivement les fichiers d'un dossier Dropbox."""
        files = []
        
        try:
            result = self.dbx.files_list_folder(folder_path, recursive=True)
            
            while True:
                for entry in result.entries:
                    if hasattr(entry, 'path_lower'):
                        ext = Path(entry.path_lower).suffix.lower()
                        if ext in extensions:
                            files.append({
                                'path': entry.path_display,
                                'path_lower': entry.path_lower,
                                'name': entry.name,
                                'size': getattr(entry, 'size', 0),
                                'modified': getattr(entry, 'server_modified', None),
                                'content_hash': getattr(entry, 'content_hash', None)
                            })
                
                if not result.has_more:
                    break
                    
                result = self.dbx.files_list_folder_continue(result.cursor)
            
            return sorted(files, key=lambda x: x['path_lower'])
            
        except Exception as e:
            logger.error(f"Erreur listage Dropbox {folder_path}: {e}")
            return []
    
    def download_file(self, file_path: str) -> Optional[bytes]:
        """Télécharge un fichier Dropbox en mémoire."""
        try:
            metadata, response = self.dbx.files_download(file_path)
            return response.content
        except Exception as e:
            logger.error(f"Erreur téléchargement {file_path}: {e}")
            return None

# === EXTRACTION DE TEXTE ===
def extract_text_from_bytes(content: bytes, filename: str) -> Optional[str]:
    """
    Extrait le texte depuis des bytes selon l'extension du fichier.
    """
    ext = Path(filename).suffix.lower()
    
    try:
        if ext in {'.txt', '.md', '.markdown', '.tex'}:
            return extract_text_plain_bytes(content)
        elif ext == '.pdf':
            return extract_text_pdf_bytes(content)
        elif ext in {'.docx'}:
            return extract_text_docx_bytes(content)
        elif ext == '.rtf':
            return extract_text_rtf_bytes(content)
        elif ext in {'.html', '.htm'}:
            return extract_text_html_bytes(content)
        elif ext in {'.json', '.xml'}:
            return extract_text_plain_bytes(content)
        else:
            logger.warning(f"Extension non supportée: {ext} pour {filename}")
            return None
    except Exception as e:
        logger.error(f"Erreur extraction {filename}: {e}")
        return None

def extract_text_plain_bytes(content: bytes) -> str:
    """Extrait le texte depuis des bytes texte brut."""
    encodings = ['utf-8', 'latin-1', 'cp1252', 'iso-8859-1']
    for encoding in encodings:
        try:
            return content.decode(encoding)
        except UnicodeDecodeError:
            continue
    raise ValueError("Impossible de décoder le fichier")

def extract_text_pdf_bytes(content: bytes) -> str:
    """Extrait le texte d'un PDF depuis des bytes."""
    try:
        import pypdf
        reader = pypdf.PdfReader(io.BytesIO(content))
        text_parts = []
        for page in reader.pages:
            text = page.extract_text()
            if text:
                text_parts.append(text)
        return "\n\n".join(text_parts)
    except ImportError:
        try:
            import pdfplumber
            with pdfplumber.open(io.BytesIO(content)) as pdf:
                text_parts = [page.extract_text() or "" for page in pdf.pages]
            return "\n\n".join(text_parts)
        except ImportError:
            logger.error("Installez pypdf ou pdfplumber")
            return None

def extract_text_docx_bytes(content: bytes) -> str:
    """Extrait le texte d'un DOCX depuis des bytes."""
    try:
        from docx import Document
        doc = Document(io.BytesIO(content))
        return "\n\n".join([para.text for para in doc.paragraphs if para.text.strip()])
    except ImportError:
        logger.error("Installez python-docx")
        return None
    except Exception as e:
        logger.warning(f"Erreur lecture DOCX: {e}")
        return None

def extract_text_rtf_bytes(content: bytes) -> str:
    """Extrait le texte d'un RTF depuis des bytes."""
    try:
        from striprtf.striprtf import rtf_to_text
        text = content.decode('utf-8', errors='ignore')
        return rtf_to_text(text)
    except ImportError:
        logger.error("Installez striprtf")
        return None

def extract_text_html_bytes(content: bytes) -> str:
    """Extrait le texte d'un HTML depuis des bytes."""
    try:
        from bs4 import BeautifulSoup
        text = content.decode('utf-8', errors='ignore')
        soup = BeautifulSoup(text, 'html.parser')
        for tag in soup(['script', 'style', 'nav', 'footer', 'header']):
            tag.decompose()
        return soup.get_text(separator='\n', strip=True)
    except ImportError:
        logger.error("Installez beautifulsoup4")
        return None

# === EXTRACTION LOCALE (ancien mode) ===
def extract_text_from_file(file_path: Path) -> Optional[str]:
    """Extrait le texte d'un fichier local."""
    try:
        content = file_path.read_bytes()
        return extract_text_from_bytes(content, file_path.name)
    except Exception as e:
        logger.error(f"Erreur lecture {file_path}: {e}")
        return None

# === GEMINI API ===
def init_gemini():
    """Initialise le client Gemini."""
    try:
        import google.generativeai as genai
        
        api_key = os.environ.get('GOOGLE_API_KEY') or os.environ.get('GEMINI_API_KEY')
        
        if not api_key:
            config_file = Path.home() / ".config" / "aiterego" / "api_keys.json"
            if config_file.exists():
                config = json.loads(config_file.read_text())
                api_key = config.get('google_api_key') or config.get('gemini_api_key')
        
        if not api_key:
            raise ValueError(
                "Clé API Google non trouvée. Définissez GOOGLE_API_KEY ou GEMINI_API_KEY"
            )
        
        genai.configure(api_key=api_key)
        return genai
    except ImportError:
        logger.error("Installez google-generativeai: pip install google-generativeai")
        sys.exit(1)

def analyze_with_gemini(genai, text: str, filename: str) -> Optional[Dict[str, Any]]:
    """Analyse un texte avec Gemini 2.5 Flash Lite."""
    model = genai.GenerativeModel('gemini-2.5-flash-lite')
    
    prompt = f"""Analyse ce document académique/de recherche et retourne un JSON structuré.

DOCUMENT: {filename}
---
{text[:50000]}
---

Retourne UNIQUEMENT un JSON valide avec cette structure exacte:
{{
    "summary": "Résumé en 2-3 phrases du contenu principal",
    "keywords": ["mot-clé1", "mot-clé2", ...],
    "entities": {{
        "persons": ["nom1", "nom2"],
        "organizations": ["org1"],
        "concepts": ["concept1", "concept2"],
        "works": ["titre1"]
    }},
    "language": "fr",
    "themes": ["thème1", "thème2"],
    "document_type": "article|thesis|notes|book|other"
}}

JSON:"""

    for attempt in range(MAX_RETRIES):
        try:
            response = model.generate_content(prompt)
            
            json_text = response.text.strip()
            if json_text.startswith('```'):
                json_text = json_text.split('```')[1]
                if json_text.startswith('json'):
                    json_text = json_text[4:]
            json_text = json_text.strip()
            
            return json.loads(json_text)
            
        except json.JSONDecodeError as e:
            logger.warning(f"Réponse JSON invalide (tentative {attempt+1}): {e}")
            if attempt < MAX_RETRIES - 1:
                time.sleep(RETRY_DELAY)
        except Exception as e:
            if "429" in str(e) or "RESOURCE_EXHAUSTED" in str(e):
                logger.warning(f"Rate limit atteint, pause de {RETRY_DELAY}s...")
                time.sleep(RETRY_DELAY * (attempt + 1))
            elif "503" in str(e) or "UNAVAILABLE" in str(e):
                logger.warning(f"Service indisponible, pause de {RETRY_DELAY * 2}s...")
                time.sleep(RETRY_DELAY * 2)
            else:
                logger.error(f"Erreur Gemini: {e}")
                if attempt == MAX_RETRIES - 1:
                    return None
    
    return None

def generate_embedding(genai, text: str) -> Optional[List[float]]:
    """Génère un embedding dense avec text-embedding-004."""
    for attempt in range(MAX_RETRIES):
        try:
            result = genai.embed_content(
                model="models/text-embedding-004",
                content=text[:10000],
                task_type="retrieval_document"
            )
            return result['embedding']
            
        except Exception as e:
            if "429" in str(e) or "RESOURCE_EXHAUSTED" in str(e):
                logger.warning(f"Rate limit embeddings, pause...")
                time.sleep(RETRY_DELAY * (attempt + 1))
            else:
                logger.error(f"Erreur embedding: {e}")
                if attempt == MAX_RETRIES - 1:
                    return None
    
    return None

# === BASE DE DONNÉES ===
def init_database(db_path: Path) -> sqlite3.Connection:
    """Initialise la base de données avec la table research_analysis."""
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    
    conn.execute("""
        CREATE TABLE IF NOT EXISTS research_analysis (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            file_path TEXT UNIQUE NOT NULL,
            file_name TEXT NOT NULL,
            file_hash TEXT NOT NULL,
            file_size INTEGER,
            mime_type TEXT,
            
            summary TEXT,
            keywords TEXT,
            entities TEXT,
            language TEXT,
            themes TEXT,
            document_type TEXT,
            
            embedding_vector BLOB,
            
            total_chunks INTEGER DEFAULT 1,
            total_chars INTEGER,
            
            indexed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            last_modified TIMESTAMP,
            indexation_version TEXT DEFAULT '2.0'
        )
    """)
    
    conn.execute("CREATE INDEX IF NOT EXISTS idx_research_keywords ON research_analysis(keywords)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_research_language ON research_analysis(language)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_research_doctype ON research_analysis(document_type)")
    
    conn.commit()
    return conn

def file_already_indexed(conn: sqlite3.Connection, file_path: str, file_hash: str) -> bool:
    """Vérifie si un fichier est déjà indexé avec le même hash."""
    cursor = conn.execute(
        "SELECT file_hash FROM research_analysis WHERE file_path = ?",
        (file_path,)
    )
    row = cursor.fetchone()
    return row is not None and row['file_hash'] == file_hash

def save_analysis(conn: sqlite3.Connection, data: Dict[str, Any]):
    """Sauvegarde l'analyse d'un fichier dans la base."""
    embedding_blob = None
    if data.get('embedding_vector'):
        import struct
        embedding_blob = struct.pack(f"{len(data['embedding_vector'])}f", *data['embedding_vector'])
    
    conn.execute("""
        INSERT OR REPLACE INTO research_analysis (
            file_path, file_name, file_hash, file_size, mime_type,
            summary, keywords, entities, language, themes, document_type,
            embedding_vector, total_chunks, total_chars, last_modified
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        data['file_path'],
        data['file_name'],
        data['file_hash'],
        data.get('file_size'),
        data.get('mime_type'),
        data.get('summary'),
        json.dumps(data.get('keywords', []), ensure_ascii=False),
        json.dumps(data.get('entities', {}), ensure_ascii=False),
        data.get('language'),
        json.dumps(data.get('themes', []), ensure_ascii=False),
        data.get('document_type'),
        embedding_blob,
        data.get('total_chunks', 1),
        data.get('total_chars'),
        data.get('last_modified')
    ))
    conn.commit()

# === CHECKPOINT ===
def load_checkpoint() -> Dict[str, Any]:
    """Charge le checkpoint de la dernière exécution."""
    if CHECKPOINT_FILE.exists():
        return json.loads(CHECKPOINT_FILE.read_text())
    return {"processed_files": [], "last_file": None, "stats": {}}

def save_checkpoint(checkpoint: Dict[str, Any]):
    """Sauvegarde le checkpoint."""
    CHECKPOINT_FILE.parent.mkdir(parents=True, exist_ok=True)
    CHECKPOINT_FILE.write_text(json.dumps(checkpoint, indent=2, ensure_ascii=False))

# === SCAN LOCAL ===
def scan_folder_local(folder: Path) -> List[Dict[str, Any]]:
    """Scanne un dossier local récursivement."""
    files = []
    for ext in SUPPORTED_EXTENSIONS:
        for f in folder.rglob(f"*{ext}"):
            files.append({
                'path': str(f),
                'path_lower': str(f).lower(),
                'name': f.name,
                'size': f.stat().st_size,
                'modified': datetime.fromtimestamp(f.stat().st_mtime).isoformat(),
                'content_hash': None  # Sera calculé à la lecture
            })
    return sorted(files, key=lambda x: x['path_lower'])

def compute_hash_from_bytes(content: bytes) -> str:
    """Calcule le hash SHA-256 de bytes."""
    return hashlib.sha256(content).hexdigest()

# === MAIN ===
def main():
    parser = argparse.ArgumentParser(description="Indexation des documents de recherche avec Gemini")
    parser.add_argument('--folder', type=str, default=DEFAULT_RESEARCH_FOLDER,
                        help="Dossier à indexer (chemin Dropbox ou local)")
    parser.add_argument('--source', type=str, choices=['dropbox', 'local'], default='dropbox',
                        help="Source des fichiers: 'dropbox' (API) ou 'local' (système de fichiers)")
    parser.add_argument('--limit', type=int, default=None,
                        help="Limiter le nombre de fichiers (pour test)")
    parser.add_argument('--resume', action='store_true',
                        help="Reprendre depuis le dernier checkpoint")
    parser.add_argument('--dry-run', action='store_true',
                        help="Afficher les fichiers sans indexer")
    args = parser.parse_args()
    
    logger.info(f"=== INDEXATION RECHERCHE 2.0 ===")
    logger.info(f"Source: {args.source.upper()}")
    logger.info(f"Dossier: {args.folder}")
    
    # Scanner les fichiers selon la source
    if args.source == 'dropbox':
        dbx_client = DropboxClient()
        files = dbx_client.list_files(args.folder, SUPPORTED_EXTENSIONS)
    else:
        folder = Path(args.folder).expanduser()
        if not folder.exists():
            logger.error(f"Dossier non trouvé: {folder}")
            sys.exit(1)
        files = scan_folder_local(folder)
        dbx_client = None
    
    logger.info(f"Fichiers trouvés: {len(files)}")
    
    if args.limit:
        files = files[:args.limit]
        logger.info(f"Limité à {args.limit} fichiers (mode test)")
    
    if args.dry_run:
        for f in files[:20]:
            print(f"  - {f['name']} ({f['size']} bytes)")
        if len(files) > 20:
            print(f"  ... et {len(files) - 20} autres")
        return
    
    # Charger checkpoint si resume
    checkpoint = load_checkpoint() if args.resume else {"processed_files": [], "stats": {}}
    processed_set = set(checkpoint.get("processed_files", []))
    
    # Initialiser Gemini et DB
    genai = init_gemini()
    conn = init_database(FILE_INDEX_DB)
    
    # Stats
    stats = {
        "total": len(files),
        "processed": 0,
        "skipped": 0,
        "errors": 0,
        "start_time": datetime.now().isoformat()
    }
    
    logger.info(f"Début de l'indexation...")
    
    for i, file_info in enumerate(files):
        file_path = file_info['path']
        file_name = file_info['name']
        
        # Skip si déjà traité (checkpoint)
        if file_path in processed_set:
            stats["skipped"] += 1
            continue
        
        logger.info(f"[{i+1}/{len(files)}] {file_name}")
        
        # Télécharger/lire le contenu
        if args.source == 'dropbox':
            content = dbx_client.download_file(file_path)
            if not content:
                logger.warning(f"  → Échec téléchargement")
                stats["errors"] += 1
                continue
        else:
            try:
                content = Path(file_path).read_bytes()
            except Exception as e:
                logger.error(f"  → Erreur lecture: {e}")
                stats["errors"] += 1
                continue
        
        # Calculer le hash
        file_hash = compute_hash_from_bytes(content)
        
        # Skip si déjà indexé avec même hash
        if file_already_indexed(conn, file_path, file_hash):
            logger.debug(f"  → Déjà indexé")
            stats["skipped"] += 1
            processed_set.add(file_path)
            continue
        
        # Extraire le texte
        text = extract_text_from_bytes(content, file_name)
        if not text or len(text.strip()) < 100:
            logger.warning(f"  → Texte insuffisant ou extraction échouée")
            stats["errors"] += 1
            continue
        
        # Analyser avec Gemini
        analysis = analyze_with_gemini(genai, text, file_name)
        if not analysis:
            logger.warning(f"  → Analyse Gemini échouée")
            stats["errors"] += 1
            continue
        
        # Générer l'embedding
        time.sleep(DELAY_BETWEEN_REQUESTS)
        embedding = generate_embedding(genai, text)
        
        # Préparer les données
        data = {
            "file_path": file_path,
            "file_name": file_name,
            "file_hash": file_hash,
            "file_size": file_info.get('size'),
            "mime_type": f"application/{Path(file_name).suffix[1:]}",
            "summary": analysis.get("summary"),
            "keywords": analysis.get("keywords", []),
            "entities": analysis.get("entities", {}),
            "language": analysis.get("language"),
            "themes": analysis.get("themes", []),
            "document_type": analysis.get("document_type"),
            "embedding_vector": embedding,
            "total_chunks": 1,
            "total_chars": len(text),
            "last_modified": file_info.get('modified')
        }
        
        # Sauvegarder
        try:
            save_analysis(conn, data)
            stats["processed"] += 1
            processed_set.add(file_path)
            logger.info(f"  → OK ({analysis.get('language', '?')}, {len(analysis.get('keywords', []))} mots-clés)")
        except Exception as e:
            logger.error(f"  → Erreur sauvegarde: {e}")
            stats["errors"] += 1
        
        # Sauvegarder checkpoint régulièrement
        if stats["processed"] % 10 == 0:
            checkpoint["processed_files"] = list(processed_set)
            checkpoint["last_file"] = file_path
            checkpoint["stats"] = stats
            save_checkpoint(checkpoint)
            logger.info(f"  [Checkpoint sauvegardé: {stats['processed']} traités]")
        
        # Rate limiting
        time.sleep(DELAY_BETWEEN_REQUESTS)
    
    # Fin
    stats["end_time"] = datetime.now().isoformat()
    checkpoint["stats"] = stats
    save_checkpoint(checkpoint)
    
    conn.close()
    
    logger.info(f"=== INDEXATION TERMINÉE ===")
    logger.info(f"Total: {stats['total']}")
    logger.info(f"Traités: {stats['processed']}")
    logger.info(f"Ignorés (déjà indexés): {stats['skipped']}")
    logger.info(f"Erreurs: {stats['errors']}")

if __name__ == "__main__":
    main()
