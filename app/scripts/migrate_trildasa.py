"""
Migration Batch Pilot — Génère les vecteurs TriLDaSA pour 1000 segments
"""
import sqlite3
import json
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).parent.parent))

from utils.trildasa_engine import TrildasaEngine

# Configuration
DB_PATH = Path.home() / "Dropbox/aiterego_memory/metadata.db"
BATCH_SIZE = 1000

def migrate_batch():
    engine = TrildasaEngine()
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row  # Permet d'accéder aux colonnes par nom
    cursor = conn.cursor()
    
    # Sélectionner 1000 segments sans vecteur
    cursor.execute("""
        SELECT * FROM metadata 
        WHERE vecteur_trildasa IS NULL OR vecteur_trildasa = ''
        LIMIT ?
    """, (BATCH_SIZE,))
    
    rows = cursor.fetchall()
    print(f"Segments à traiter: {len(rows)}")
    
    updated = 0
    for row in rows:
        row_dict = dict(row)
        vector = engine.generate_vector(row_dict)
        
        if vector:
            cursor.execute("""
                UPDATE metadata 
                SET vecteur_trildasa = ? 
                WHERE id = ?
            """, (json.dumps(vector), row_dict['id']))
            updated += 1
            
            if updated % 100 == 0:
                print(f"  {updated} segments traités...")
    
    conn.commit()
    conn.close()
    print(f"\n✅ Migration terminée: {updated} vecteurs générés")

if __name__ == "__main__":
    migrate_batch()