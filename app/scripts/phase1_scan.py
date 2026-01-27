import os
import sqlite3
import time
from pathlib import Path

# Configuration des chemins
DROPBOX_PATH = os.path.expanduser("~/Dropbox")
DB_DIR = os.path.expanduser("~/Dropbox/aiterego_memory/index")
DB_PATH = os.path.join(DB_DIR, "file_index.db")

def init_db():
    # Créer le dossier d'index s'il n'existe pas
    os.makedirs(DB_DIR, exist_ok=True)
    
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    # Table principale (Métadonnées techniques)
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS files (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            path TEXT UNIQUE,
            name TEXT,
            extension TEXT,
            size INTEGER,
            mtime REAL,
            domain TEXT,
            summary TEXT,
            roget_codes TEXT,
            importance INTEGER DEFAULT 3,
            status TEXT DEFAULT 'pending' -- 'pending', 'indexed', 'error'
        )
    ''')
    
    # Table FTS5 pour la recherche ultra-rapide sur les noms et chemins
    cursor.execute('''
        CREATE VIRTUAL TABLE IF NOT EXISTS files_fts USING fts5(
            path, 
            name, 
            content='files', 
            content_rowid='id'
        )
    ''')
    
    # Triggers pour synchroniser FTS5 avec la table principale
    cursor.execute('''
        CREATE TRIGGER IF NOT EXISTS files_ai AFTER INSERT ON files BEGIN
            INSERT INTO files_fts(rowid, path, name) VALUES (new.id, new.path, new.name);
        END;
    ''')
    
    conn.commit()
    return conn

def scan_dropbox(conn):
    cursor = conn.cursor()
    start_time = time.time()
    count = 0
    
    print(f"Démarrage du scan technique : {DROPBOX_PATH}")
    
    for root, dirs, files in os.walk(DROPBOX_PATH):
        # Ignorer les dossiers système et cachés
        dirs[:] = [d for d in dirs if not d.startswith('.') and d not in ['node_modules', '__pycache__']]
        
        for file in files:
            if file.startswith('.'): continue
            
            full_path = os.path.join(root, file)
            p = Path(full_path)
            
            try:
                stat = p.stat()
                cursor.execute('''
                    INSERT OR IGNORE INTO files (path, name, extension, size, mtime)
                    VALUES (?, ?, ?, ?, ?)
                ''', (full_path, p.name, p.suffix.lower(), stat.st_size, stat.st_mtime))
                
                count += 1
                if count % 1000 == 0:
                    conn.commit()
                    print(f"Fichiers répertoriés : {count}...")
                    
            except Exception as e:
                print(f"Erreur sur {full_path}: {e}")
                continue

    conn.commit()
    duration = time.time() - start_time
    print(f"Phase 1 terminée en {duration:.2f} secondes.")
    print(f"Total : {count} fichiers enregistrés dans file_index.db.")

if __name__ == "__main__":
    connection = init_db()
    scan_dropbox(connection)
    connection.close()