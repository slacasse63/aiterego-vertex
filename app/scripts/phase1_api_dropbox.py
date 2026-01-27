"""
phase1_api_dropbox.py - Indexation Dropbox via API (cloud-native)
MOSS v0.11.5

Remplace le scan local par une indexation directe via l'API Dropbox.
Utilise file_id comme identifiant unique (portabilité entre machines).

Avantages:
- Source de vérité unique (cloud)
- Indépendant de la synchronisation locale
- file_id immuable (survit aux renommages/déplacements)

Usage:
    python3 phase1_api_dropbox.py

Auteurs: Serge Lacasse, Claude, Iris
Date: 2026-01-16
"""

import os
import sqlite3
import time
import logging
from pathlib import Path
from datetime import datetime
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
    from dropbox.exceptions import ApiError, AuthError
    from dropbox.files import FileMetadata, FolderMetadata
    DROPBOX_AVAILABLE = True
except ImportError:
    DROPBOX_AVAILABLE = False
    logger.error("dropbox SDK non installé. Exécuter: pip3 install dropbox")

# Configuration
DB_DIR = Path.home() / "Dropbox" / "aiterego_memory" / "index"
DB_PATH = DB_DIR / "file_index.db"
BATCH_SIZE = 2000  # Nombre d'entrées Dropbox par requête (max 2000)
COMMIT_EVERY = 1000  # Commit DB tous les N fichiers


def init_db() -> sqlite3.Connection:
    """Initialise la base de données avec le nouveau schéma (file_id comme clé)."""
    DB_DIR.mkdir(parents=True, exist_ok=True)
    
    conn = sqlite3.connect(str(DB_PATH))
    cursor = conn.cursor()
    
    # Supprimer l'ancienne table si elle existe (migration)
    cursor.execute("DROP TABLE IF EXISTS files_fts")
    cursor.execute("DROP TABLE IF EXISTS files")
    
    # Nouvelle table avec file_id comme identifiant unique
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS files (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            file_id TEXT UNIQUE NOT NULL,
            path_display TEXT NOT NULL,
            path_lower TEXT NOT NULL,
            name TEXT NOT NULL,
            extension TEXT,
            size INTEGER,
            content_hash TEXT,
            server_modified TEXT,
            client_modified TEXT,
            rev TEXT,
            is_downloadable INTEGER DEFAULT 1,
            domain TEXT,
            summary TEXT,
            roget_codes TEXT,
            keywords TEXT,
            importance INTEGER DEFAULT 3,
            status TEXT DEFAULT 'pending',
            indexed_at TEXT,
            enriched_at TEXT,
            error_message TEXT
        )
    ''')
    
    # Index pour performances
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_files_path ON files(path_lower)')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_files_extension ON files(extension)')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_files_status ON files(status)')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_files_domain ON files(domain)')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_files_content_hash ON files(content_hash)')
    
    # Table FTS5 pour recherche textuelle
    cursor.execute('''
        CREATE VIRTUAL TABLE IF NOT EXISTS files_fts USING fts5(
            path_display,
            name,
            summary,
            keywords,
            content='files',
            content_rowid='id'
        )
    ''')
    
    # Triggers pour synchroniser FTS5
    cursor.execute('''
        CREATE TRIGGER IF NOT EXISTS files_ai AFTER INSERT ON files BEGIN
            INSERT INTO files_fts(rowid, path_display, name, summary, keywords)
            VALUES (new.id, new.path_display, new.name, new.summary, new.keywords);
        END
    ''')
    
    cursor.execute('''
        CREATE TRIGGER IF NOT EXISTS files_ad AFTER DELETE ON files BEGIN
            INSERT INTO files_fts(files_fts, rowid, path_display, name, summary, keywords)
            VALUES ('delete', old.id, old.path_display, old.name, old.summary, old.keywords);
        END
    ''')
    
    cursor.execute('''
        CREATE TRIGGER IF NOT EXISTS files_au AFTER UPDATE ON files BEGIN
            INSERT INTO files_fts(files_fts, rowid, path_display, name, summary, keywords)
            VALUES ('delete', old.id, old.path_display, old.name, old.summary, old.keywords);
            INSERT INTO files_fts(rowid, path_display, name, summary, keywords)
            VALUES (new.id, new.path_display, new.name, new.summary, new.keywords);
        END
    ''')
    
    conn.commit()
    logger.info(f"Base de données initialisée: {DB_PATH}")
    return conn


def get_dropbox_client() -> dropbox.Dropbox:
    """Crée et retourne un client Dropbox authentifié."""
    token = os.getenv("DROPBOX_ACCESS_TOKEN")
    
    if not token:
        raise ValueError("DROPBOX_ACCESS_TOKEN non trouvé dans .env")
    
    # Nettoyer le token (enlever espaces/newlines)
    token = token.strip()
    
    dbx = dropbox.Dropbox(token)
    
    # Vérifier l'authentification
    try:
        account = dbx.users_get_current_account()
        logger.info(f"Connecté à Dropbox: {account.email}")
        return dbx
    except AuthError as e:
        raise ValueError(f"Token Dropbox invalide: {e}")


def scan_dropbox_api(conn: sqlite3.Connection, dbx: dropbox.Dropbox):
    """Scanne tout le Dropbox via l'API et enregistre dans la DB."""
    cursor = conn.cursor()
    start_time = time.time()
    total_files = 0
    total_folders = 0
    errors = 0
    
    logger.info("Démarrage du scan Dropbox via API...")
    logger.info(f"Batch size: {BATCH_SIZE} entrées par requête")
    
    # Timestamp d'indexation
    indexed_at = datetime.now().isoformat()
    
    try:
        # Premier appel - liste récursive depuis la racine
        result = dbx.files_list_folder("", recursive=True, limit=BATCH_SIZE)
        
        while True:
            # Traiter les entrées
            for entry in result.entries:
                if isinstance(entry, FileMetadata):
                    # C'est un fichier
                    ext = Path(entry.name).suffix.lower() if '.' in entry.name else ''
                    
                    try:
                        cursor.execute('''
                            INSERT OR REPLACE INTO files (
                                file_id, path_display, path_lower, name, extension,
                                size, content_hash, server_modified, client_modified,
                                rev, is_downloadable, status, indexed_at
                            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'pending', ?)
                        ''', (
                            entry.id,
                            entry.path_display,
                            entry.path_lower,
                            entry.name,
                            ext,
                            entry.size,
                            entry.content_hash,
                            entry.server_modified.isoformat() if entry.server_modified else None,
                            entry.client_modified.isoformat() if entry.client_modified else None,
                            entry.rev,
                            1 if entry.is_downloadable else 0,
                            indexed_at
                        ))
                        total_files += 1
                        
                    except Exception as e:
                        errors += 1
                        logger.warning(f"Erreur insertion {entry.path_display}: {e}")
                
                elif isinstance(entry, FolderMetadata):
                    total_folders += 1
                
                # Commit périodique
                if total_files % COMMIT_EVERY == 0 and total_files > 0:
                    conn.commit()
                    logger.info(f"Progression: {total_files} fichiers, {total_folders} dossiers...")
            
            # Vérifier s'il y a plus de résultats
            if not result.has_more:
                break
            
            # Continuer avec le curseur
            result = dbx.files_list_folder_continue(result.cursor)
        
        # Commit final
        conn.commit()
        
    except ApiError as e:
        logger.error(f"Erreur API Dropbox: {e}")
        raise
    
    duration = time.time() - start_time
    
    logger.info("=" * 60)
    logger.info("SCAN TERMINÉ")
    logger.info("=" * 60)
    logger.info(f"Durée: {duration:.2f} secondes")
    logger.info(f"Fichiers indexés: {total_files}")
    logger.info(f"Dossiers traversés: {total_folders}")
    logger.info(f"Erreurs: {errors}")
    logger.info(f"Base de données: {DB_PATH}")
    
    return total_files


def print_stats(conn: sqlite3.Connection):
    """Affiche des statistiques sur les fichiers indexés."""
    cursor = conn.cursor()
    
    # Total par extension
    cursor.execute('''
        SELECT extension, COUNT(*) as count, SUM(size) as total_size
        FROM files
        WHERE extension != ''
        GROUP BY extension
        ORDER BY count DESC
        LIMIT 20
    ''')
    
    print("\n📊 Top 20 extensions:")
    print("-" * 50)
    for row in cursor.fetchall():
        ext, count, size = row
        size_mb = (size or 0) / (1024 * 1024)
        print(f"  {ext:10} : {count:>8} fichiers ({size_mb:>10.1f} MB)")
    
    # Total
    cursor.execute('SELECT COUNT(*), SUM(size) FROM files')
    total_count, total_size = cursor.fetchone()
    total_gb = (total_size or 0) / (1024 * 1024 * 1024)
    print("-" * 50)
    print(f"  {'TOTAL':10} : {total_count:>8} fichiers ({total_gb:>10.2f} GB)")


def main():
    """Point d'entrée principal."""
    print("=" * 60)
    print("PHASE 1 - INDEXATION DROPBOX VIA API")
    print("=" * 60)
    
    if not DROPBOX_AVAILABLE:
        print("\n❌ Erreur: SDK Dropbox non installé")
        print("   Exécuter: pip3 install dropbox")
        return
    
    # Initialiser la DB
    conn = init_db()
    
    try:
        # Connexion Dropbox
        dbx = get_dropbox_client()
        
        # Scanner
        total = scan_dropbox_api(conn, dbx)
        
        # Statistiques
        if total > 0:
            print_stats(conn)
        
        print("\n✅ Phase 1 terminée avec succès!")
        print(f"   Prochaine étape: Phase 2 (enrichissement Mistral)")
        
    except Exception as e:
        logger.error(f"Erreur fatale: {e}")
        print(f"\n❌ Erreur: {e}")
        
    finally:
        conn.close()


if __name__ == "__main__":
    main()
