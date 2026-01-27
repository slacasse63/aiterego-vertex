"""
phase2_mistral.py - Enrichissement des fichiers via Mistral local
MOSS v0.11.5

Lit les fichiers de file_index.db (status='pending') et les enrichit avec Mistral:
- Résumé du contenu
- Codes Roget (classification thématique)
- Domaine (personnel, recherche, technique, administratif, créatif)
- Mots-clés

Utilise Ollama + Mistral en local pour confidentialité et coût zéro.

Usage:
    python3 phase2_mistral.py [--limit N] [--extensions .pdf,.docx,.md]

Options:
    --limit N          : Traiter seulement N fichiers (pour test)
    --extensions       : Filtrer par extensions (défaut: tous les textes)
    --resume           : Reprendre là où on s'est arrêté (skip enriched)

Auteurs: Serge Lacasse, Claude, Iris
Date: 2026-01-16
"""

import os
import sys
import json
import sqlite3
import time
import logging
import argparse
import tempfile
from pathlib import Path
from datetime import datetime
from typing import Optional, Dict, Any, List

from dotenv import load_dotenv

# Charger les variables d'environnement
env_path = Path.home() / "Dropbox" / "aiterego" / ".env"
load_dotenv(env_path)

# Configuration logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    datefmt='%H:%M:%S'
)
logger = logging.getLogger(__name__)

# Import Dropbox SDK
try:
    import dropbox
    from dropbox.exceptions import ApiError
    DROPBOX_AVAILABLE = True
except ImportError:
    DROPBOX_AVAILABLE = False
    logger.warning("dropbox SDK non disponible - téléchargement cloud désactivé")

# Import requests pour Ollama
try:
    import requests
    REQUESTS_AVAILABLE = True
except ImportError:
    REQUESTS_AVAILABLE = False
    print("❌ requests non installé. Exécuter: pip3 install requests")
    exit(1)

# Configuration
DB_PATH = Path.home() / "Dropbox" / "aiterego_memory" / "index" / "file_index.db"
OLLAMA_URL = "http://localhost:11434/api/generate"
OLLAMA_MODEL = "mistral"
TEMP_DIR = Path(tempfile.gettempdir()) / "moss_phase2"

# Extensions à traiter (fichiers textuels)
TEXT_EXTENSIONS = {
    '.txt', '.md', '.py', '.json', '.yaml', '.yml', '.csv',
    '.html', '.css', '.js', '.sql', '.sh', '.xml',
    '.pdf', '.doc', '.docx', '.rtf'
}

# Limites
MAX_CONTENT_SIZE = 50000  # Caractères max à envoyer à Mistral
TIMEOUT_SECONDS = 120  # Timeout par fichier


def get_dropbox_client() -> Optional[dropbox.Dropbox]:
    """Crée un client Dropbox avec refresh token (ne expire jamais)."""
    if not DROPBOX_AVAILABLE:
        return None
    
    app_key = os.getenv("DROPBOX_APP_KEY")
    app_secret = os.getenv("DROPBOX_APP_SECRET")
    refresh_token = os.getenv("DROPBOX_REFRESH_TOKEN")
    
    if not all([app_key, app_secret, refresh_token]):
        logger.warning("Variables DROPBOX_APP_KEY, DROPBOX_APP_SECRET, DROPBOX_REFRESH_TOKEN manquantes")
        return None
    
    try:
        dbx = dropbox.Dropbox(
            oauth2_refresh_token=refresh_token,
            app_key=app_key,
            app_secret=app_secret
        )
        dbx.users_get_current_account()  # Test connexion
        return dbx
    except Exception as e:
        logger.warning(f"Connexion Dropbox échouée: {e}")
        return None


def download_file_content(dbx: dropbox.Dropbox, path_lower: str, max_retries: int = 3) -> Optional[str]:
    """Télécharge et retourne le contenu d'un fichier depuis Dropbox avec retry."""
    for attempt in range(max_retries):
        try:
            metadata, response = dbx.files_download(path_lower)
            content = response.content
            
            # Essayer de décoder en texte
            for encoding in ['utf-8', 'latin-1', 'cp1252']:
                try:
                    return content.decode(encoding)
                except UnicodeDecodeError:
                    continue
            
            return None  # Fichier binaire
            
        except ApiError as e:
            logger.debug(f"Erreur téléchargement {path_lower}: {e}")
            return None
        except Exception as e:
            if attempt < max_retries - 1:
                wait_time = (attempt + 1) * 10  # 10s, 20s, 30s
                logger.warning(f"Connexion échouée, retry {attempt + 1}/{max_retries} dans {wait_time}s...")
                time.sleep(wait_time)
            else:
                logger.warning(f"Échec après {max_retries} tentatives: {path_lower}")
                return None
    return None


def read_local_file(path: str) -> Optional[str]:
    """Lit un fichier local si disponible."""
    # Convertir le path Dropbox en path local
    local_path = Path.home() / "Dropbox" / path.lstrip('/')
    
    if not local_path.exists():
        return None
    
    try:
        for encoding in ['utf-8', 'latin-1', 'cp1252']:
            try:
                return local_path.read_text(encoding=encoding)
            except UnicodeDecodeError:
                continue
        return None
    except Exception:
        return None


def extract_text_from_pdf(content: bytes) -> Optional[str]:
    """Extrait le texte d'un PDF (si PyPDF2 disponible)."""
    try:
        import PyPDF2
        import io
        
        reader = PyPDF2.PdfReader(io.BytesIO(content))
        text_parts = []
        for page in reader.pages[:20]:  # Max 20 pages
            text = page.extract_text()
            if text:
                text_parts.append(text)
        
        return "\n\n".join(text_parts) if text_parts else None
    except Exception:
        return None


def get_file_content(dbx: Optional[dropbox.Dropbox], path_lower: str, path_display: str, extension: str) -> Optional[str]:
    """Récupère le contenu d'un fichier (local ou cloud)."""
    
    # Essayer d'abord local
    content = read_local_file(path_display)
    
    # Sinon télécharger depuis Dropbox
    if content is None and dbx:
        content = download_file_content(dbx, path_lower)
    
    if content is None:
        return None
    
    # Tronquer si trop long
    if len(content) > MAX_CONTENT_SIZE:
        content = content[:MAX_CONTENT_SIZE] + "\n\n[... tronqué ...]"
    
    return content


def call_mistral(prompt: str) -> Optional[str]:
    """Appelle Mistral via Ollama."""
    try:
        response = requests.post(
            OLLAMA_URL,
            json={
                "model": OLLAMA_MODEL,
                "prompt": prompt,
                "stream": False,
                "options": {
                    "temperature": 0.3,
                    "num_predict": 1000
                }
            },
            timeout=TIMEOUT_SECONDS
        )
        
        if response.status_code == 200:
            return response.json().get("response", "")
        else:
            logger.warning(f"Ollama error {response.status_code}")
            return None
            
    except requests.exceptions.Timeout:
        logger.warning("Timeout Mistral")
        return None
    except Exception as e:
        logger.warning(f"Erreur Mistral: {e}")
        return None


def enrich_file(content: str, filename: str, extension: str) -> Dict[str, Any]:
    """Enrichit un fichier avec Mistral."""
    
    prompt = f"""Analyse ce fichier et réponds en JSON valide uniquement.

FICHIER: {filename}
TYPE: {extension}

CONTENU:
---
{content[:30000]}
---

Réponds UNIQUEMENT avec ce JSON (pas de texte avant/après):
{{
    "summary": "Résumé en 1-2 phrases du contenu principal",
    "domain": "personnel|recherche|technique|administratif|creatif|media",
    "keywords": ["mot1", "mot2", "mot3"],
    "roget_primary": "XX-XXXX-XXXX",
    "importance": 3
}}

Règles:
- domain: choisis UN seul parmi les options
- keywords: 3-5 mots-clés pertinents
- roget_primary: code Roget principal (ex: "04-0110-0010" pour cognition)
- importance: 1 (trivial) à 5 (critique)
- summary: en français, concis
"""

    response = call_mistral(prompt)
    
    if not response:
        return {"error": "Pas de réponse Mistral"}
    
    # Parser le JSON
    try:
        # Nettoyer la réponse
        response = response.strip()
        
        # Trouver le JSON dans la réponse
        start = response.find('{')
        end = response.rfind('}') + 1
        
        if start >= 0 and end > start:
            json_str = response[start:end]
            return json.loads(json_str)
        else:
            return {"error": "JSON non trouvé", "raw": response[:200]}
            
    except json.JSONDecodeError as e:
        return {"error": f"JSON invalide: {e}", "raw": response[:200]}


def process_files(conn: sqlite3.Connection, dbx: Optional[dropbox.Dropbox], 
                  limit: Optional[int] = None, extensions: Optional[set] = None):
    """Traite les fichiers en attente."""
    
    cursor = conn.cursor()
    
    # Construire la requête
    query = "SELECT id, file_id, path_lower, path_display, name, extension FROM files WHERE status = 'pending'"
    params = []
    
    if extensions:
        placeholders = ','.join(['?' for _ in extensions])
        query += f" AND extension IN ({placeholders})"
        params.extend(extensions)
    
    if limit:
        query += f" LIMIT {limit}"
    
    cursor.execute(query, params)
    files = cursor.fetchall()
    
    total = len(files)
    logger.info(f"Fichiers à traiter: {total}")
    
    if total == 0:
        logger.info("Aucun fichier en attente.")
        return
    
    processed = 0
    enriched = 0
    errors = 0
    skipped = 0
    
    start_time = time.time()
    
    for row in files:
        file_id_db, file_id, path_lower, path_display, name, extension = row
        
        processed += 1
        
        # Afficher le fichier en cours
        logger.info(f"[{processed}/{total}] {name}")
        
        # Skip si extension non supportée
        if extension and extension.lower() not in TEXT_EXTENSIONS:
            cursor.execute(
                "UPDATE files SET status = 'skipped', enriched_at = ? WHERE id = ?",
                (datetime.now().isoformat(), file_id_db)
            )
            skipped += 1
            continue
        
        # Récupérer le contenu
        content = get_file_content(dbx, path_lower, path_display, extension)
        
        if not content:
            cursor.execute(
                "UPDATE files SET status = 'no_content', enriched_at = ? WHERE id = ?",
                (datetime.now().isoformat(), file_id_db)
            )
            skipped += 1
            continue
        
        # Enrichir avec Mistral
        result = enrich_file(content, name, extension)
        
        if "error" in result:
            cursor.execute(
                "UPDATE files SET status = 'error', error_message = ?, enriched_at = ? WHERE id = ?",
                (result.get("error", "")[:500], datetime.now().isoformat(), file_id_db)
            )
            errors += 1
        else:
             # Préparer les données
            keywords = result.get("keywords", [])
            if isinstance(keywords, list):
                keywords = json.dumps(keywords, ensure_ascii=False)
            elif not isinstance(keywords, str):
                keywords = ""
            
            domain = result.get("domain", "")
            if isinstance(domain, list):
                domain = domain[0] if domain else ""
            elif not isinstance(domain, str):
                domain = ""
            
            summary = result.get("summary", "")
            if not isinstance(summary, str):
                summary = str(summary) if summary else ""
            
            roget = result.get("roget_primary", "")
            if not isinstance(roget, str):
                roget = str(roget) if roget else ""
            
            importance = result.get("importance", 3)
            if not isinstance(importance, int):
                try:
                    importance = int(importance)
                except:
                    importance = 3

            cursor.execute('''
                UPDATE files SET 
                    summary = ?,
                    domain = ?,
                    keywords = ?,
                    roget_codes = ?,
                    importance = ?,
                    status = 'enriched',
                    enriched_at = ?
                WHERE id = ?
            ''', (
                summary,
                domain,
                keywords,
                roget,
                importance,
                datetime.now().isoformat(),
                file_id_db
            ))
            enriched += 1
        
        # Commit périodique
        if processed % 10 == 0:
            conn.commit()
            elapsed = time.time() - start_time
            rate = processed / elapsed if elapsed > 0 else 0
            eta = (total - processed) / rate if rate > 0 else 0
            logger.info(f"Progression: {processed}/{total} ({enriched} enrichis, {errors} erreurs) - ETA: {eta/60:.1f} min")
    
    conn.commit()
    
    elapsed = time.time() - start_time
    
    logger.info("=" * 60)
    logger.info("PHASE 2 TERMINÉE")
    logger.info("=" * 60)
    logger.info(f"Durée: {elapsed/60:.1f} minutes")
    logger.info(f"Traités: {processed}")
    logger.info(f"Enrichis: {enriched}")
    logger.info(f"Skipped: {skipped}")
    logger.info(f"Erreurs: {errors}")


def check_ollama():
    """Vérifie que Ollama est accessible."""
    try:
        response = requests.get("http://localhost:11434/api/tags", timeout=5)
        if response.status_code == 200:
            models = [m["name"] for m in response.json().get("models", [])]
            if any(OLLAMA_MODEL in m for m in models):
                logger.info(f"✅ Ollama OK - Modèle {OLLAMA_MODEL} disponible")
                return True
            else:
                logger.error(f"❌ Modèle {OLLAMA_MODEL} non trouvé. Modèles: {models}")
                return False
        return False
    except Exception as e:
        logger.error(f"❌ Ollama non accessible: {e}")
        logger.error("   Lancer: ollama serve")
        return False


def main():
    parser = argparse.ArgumentParser(description="Phase 2 - Enrichissement Mistral")
    parser.add_argument("--limit", type=int, help="Nombre max de fichiers à traiter")
    parser.add_argument("--extensions", type=str, help="Extensions à traiter (ex: .pdf,.docx)")
    args = parser.parse_args()
    
    print("=" * 60)
    print("PHASE 2 - ENRICHISSEMENT MISTRAL")
    print("=" * 60)
    
    # Vérifier Ollama
    if not check_ollama():
        print("\n❌ Ollama doit être lancé. Exécuter: ollama serve")
        sys.exit(1)
    
    # Vérifier la DB
    if not DB_PATH.exists():
        print(f"\n❌ Base de données non trouvée: {DB_PATH}")
        print("   Lancer d'abord: python3 phase1_api_dropbox.py")
        sys.exit(1)
    
    # Connexion DB
    conn = sqlite3.connect(str(DB_PATH))
    
    # Client Dropbox (optionnel)
    dbx = get_dropbox_client()
    if dbx:
        logger.info("✅ Connexion Dropbox OK")
    else:
        logger.warning("⚠️ Dropbox non disponible - fichiers locaux uniquement")
    
    # Extensions à traiter
    extensions = None
    if args.extensions:
        extensions = set(ext.strip() for ext in args.extensions.split(','))
        logger.info(f"Extensions filtrées: {extensions}")
    
    try:
        process_files(conn, dbx, limit=args.limit, extensions=extensions)
    except KeyboardInterrupt:
        logger.info("\n⚠️ Interruption - progression sauvegardée")
        conn.commit()
    finally:
        conn.close()
    
    print("\n✅ Phase 2 terminée!")


if __name__ == "__main__":
    main()
