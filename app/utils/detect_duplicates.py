#!/usr/bin/env python3
"""
Détection et nettoyage des doublons dans metadata.db

Usage:
    python detect_duplicates.py              # Affiche les doublons
    python detect_duplicates.py --delete     # Supprime les doublons (garde le premier)
    python detect_duplicates.py --details    # Affiche les détails de chaque doublon
"""

import sqlite3
import argparse
from pathlib import Path

# === CONFIGURATION ===
DB_PATH = Path.home() / "Dropbox" / "aiterego_memory" / "metadata.db"

def get_connection():
    if not DB_PATH.exists():
        print(f"❌ Base introuvable: {DB_PATH}")
        exit(1)
    return sqlite3.connect(DB_PATH)

def detect_duplicates(show_details=False):
    """Détecte les doublons (même timestamp + même source_origine)"""
    conn = get_connection()
    cursor = conn.cursor()
    
    # Trouver les combinaisons timestamp+source qui apparaissent plus d'une fois
    cursor.execute('''
        SELECT timestamp, source_origine, COUNT(*) as count
        FROM metadata
        GROUP BY timestamp, source_origine
        HAVING COUNT(*) > 1
        ORDER BY count DESC, timestamp
    ''')
    
    duplicates = cursor.fetchall()
    
    if not duplicates:
        print("✅ Aucun doublon trouvé !")
        conn.close()
        return []
    
    print(f"\n{'='*60}")
    print(f"🔍 DOUBLONS DÉTECTÉS")
    print(f"{'='*60}")
    
    total_duplicates = 0
    total_to_delete = 0
    
    for timestamp, source, count in duplicates:
        extra = count - 1  # Nombre de doublons à supprimer (on garde 1)
        total_duplicates += count
        total_to_delete += extra
        print(f"   {timestamp} | {source} | {count}x (+{extra} à supprimer)")
        
        if show_details:
            cursor.execute('''
                SELECT id, resume_texte, auteur
                FROM metadata
                WHERE timestamp = ? AND source_origine = ?
                ORDER BY id
            ''', (timestamp, source))
            rows = cursor.fetchall()
            for row in rows:
                resume = (row[1][:50] + "...") if row[1] and len(row[1]) > 50 else row[1]
                print(f"      └─ ID {row[0]} | {row[2]} | {resume}")
    
    print(f"\n{'─'*60}")
    print(f"📊 Résumé:")
    print(f"   Combinaisons en doublon: {len(duplicates)}")
    print(f"   Segments totaux concernés: {total_duplicates}")
    print(f"   Segments à supprimer: {total_to_delete}")
    print(f"{'='*60}\n")
    
    conn.close()
    return duplicates

def delete_duplicates(dry_run=True):
    """Supprime les doublons en gardant le premier (ID le plus bas)"""
    conn = get_connection()
    cursor = conn.cursor()
    
    # Trouver tous les IDs à supprimer (garder le MIN(id) pour chaque groupe)
    cursor.execute('''
        SELECT id FROM metadata
        WHERE id NOT IN (
            SELECT MIN(id)
            FROM metadata
            GROUP BY timestamp, source_origine
        )
        AND (timestamp, source_origine) IN (
            SELECT timestamp, source_origine
            FROM metadata
            GROUP BY timestamp, source_origine
            HAVING COUNT(*) > 1
        )
    ''')
    
    ids_to_delete = [row[0] for row in cursor.fetchall()]
    
    if not ids_to_delete:
        print("✅ Aucun doublon à supprimer !")
        conn.close()
        return 0
    
    if dry_run:
        print(f"\n🔍 [DRY-RUN] {len(ids_to_delete)} segments seraient supprimés:")
        print(f"   IDs: {ids_to_delete[:20]}{'...' if len(ids_to_delete) > 20 else ''}")
        conn.close()
        return len(ids_to_delete)
    
    # Vraie suppression
    print(f"\n🗑️ Suppression de {len(ids_to_delete)} doublons...")
    
    cursor.execute(f'''
        DELETE FROM metadata
        WHERE id IN ({','.join('?' * len(ids_to_delete))})
    ''', ids_to_delete)
    
    deleted = cursor.rowcount
    conn.commit()
    conn.close()
    
    print(f"✅ {deleted} doublons supprimés !")
    return deleted

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Détection et nettoyage des doublons")
    parser.add_argument("--details", "-d", action="store_true", help="Afficher les détails de chaque doublon")
    parser.add_argument("--delete", action="store_true", help="Supprimer les doublons (garde le premier)")
    parser.add_argument("--force", "-f", action="store_true", help="Supprimer sans confirmation")
    
    args = parser.parse_args()
    
    # Toujours afficher les doublons d'abord
    duplicates = detect_duplicates(show_details=args.details)
    
    if args.delete and duplicates:
        if args.force:
            delete_duplicates(dry_run=False)
        else:
            # Dry run d'abord
            count = delete_duplicates(dry_run=True)
            
            # Demander confirmation
            response = input(f"\n⚠️ Confirmer la suppression de {count} doublons ? (oui/non): ")
            if response.lower() in ['oui', 'o', 'yes', 'y']:
                delete_duplicates(dry_run=False)
            else:
                print("❌ Suppression annulée.")