"""
scribe_rattrapage.py - Rattrapage des segments échoués (confidence_score = 0.5)
MOSS v0.10.3 - Session 69

Réessaye l'extraction de métadonnées pour les segments où Gemini a échoué.

Usage:
    python -m app.agents.scribe_rattrapage --limit 100        # Traite 100 segments
    python -m app.agents.scribe_rattrapage --all              # Traite tous les échoués
    python -m app.agents.scribe_rattrapage --dry-run          # Affiche sans exécuter
    python -m app.agents.scribe_rattrapage --source-file "2025-03-01"  # Filtre par fichier
"""

import sqlite3
import argparse
import time
import re
from pathlib import Path
from typing import List, Dict, Any, Optional

# Configuration
MEMORY_PATH = Path.home() / "Dropbox" / "aiterego_memory"
DB_PATH = MEMORY_PATH / "metadata.db"
ECHANGES_PATH = MEMORY_PATH / "echanges"

# Import de l'extracteur
import sys
sys.path.insert(0, str(Path(__file__).parent.parent))
from agents.extractors import GeminiExtractor
from utils.trildasa_engine import TrildasaEngine

# Version
VERSION = "1.0"


class ScribeRattrapage:
    """
    Rattrape les segments avec confidence_score = 0.5 (extraction échouée)
    """
    
    def __init__(self, dry_run: bool = False, batch_size: int = 5):
        self.dry_run = dry_run
        self.batch_size = batch_size
        self.conn = sqlite3.connect(DB_PATH)
        self.conn.row_factory = sqlite3.Row
        
        if not dry_run:
            self.extractor = GeminiExtractor(batch_size=batch_size)
            
            # TriLDaSA
            tag_index_path = Path.home() / "Dropbox" / "aiterego" / "index" / "tag_index_numbered.json"
            self.trildasa = TrildasaEngine(str(tag_index_path))
        
        print(f"{'🔍 MODE DRY-RUN' if dry_run else f'🔧 ScribeRattrapage v{VERSION}'}")
    
    def get_failed_segments(self, limit: Optional[int] = None, source_filter: Optional[str] = None) -> List[Dict]:
        """
        Récupère les segments avec confidence_score = 0.5
        """
        cursor = self.conn.cursor()
        
        query = """
            SELECT id, timestamp, token_start, token_end, source_file, auteur
            FROM metadata 
            WHERE confidence_score = 0.5
        """
        
        if source_filter:
            query += f" AND source_file LIKE '%{source_filter}%'"
        
        query += " ORDER BY timestamp ASC"
        
        if limit:
            query += f" LIMIT {limit}"
        
        cursor.execute(query)
        rows = cursor.fetchall()
        
        return [dict(row) for row in rows]
    
    def read_segment_text(self, source_file: str, token_start: int, token_end: int) -> Optional[str]:
        """
        Lit le texte original d'un segment depuis le fichier source.
        Le format est: TOKEN_START|[SOURCE:xxx][timestamp] Auteur: texte
        """
        file_path = ECHANGES_PATH / source_file.replace("echanges/", "")
        
        if not file_path.exists():
            print(f"   ⚠️ Fichier non trouvé: {file_path}")
            return None
        
        try:
            content = file_path.read_text(encoding='utf-8')
            
            # Chercher la ligne qui commence par le token_start
            pattern = rf'^{token_start}\|(.+?)(?=\n\d+\||$)'
            match = re.search(pattern, content, re.MULTILINE | re.DOTALL)
            
            if match:
                line = match.group(0)
                # Extraire le texte après le marqueur [timestamp] Auteur:
                text_match = re.search(r'\]\s*(?:human|assistant|utilisateur|AIter Ego|Human|Assistant)\s*:\s*(.+)', line, re.IGNORECASE | re.DOTALL)
                if text_match:
                    return text_match.group(1).strip()
                else:
                    # Retourner tout après le |
                    return line.split('|', 1)[1].strip() if '|' in line else line.strip()
            
            # Fallback: chercher par plage de tokens
            lines = content.split('\n')
            for line in lines:
                if line.startswith(f"{token_start}|"):
                    text_part = line.split('|', 1)[1] if '|' in line else line
                    # Extraire le texte après le format [SOURCE:...][timestamp] Auteur:
                    clean_match = re.search(r'\]\s*(?:human|assistant|utilisateur|AIter Ego)\s*:\s*(.+)', text_part, re.IGNORECASE | re.DOTALL)
                    if clean_match:
                        return clean_match.group(1).strip()
                    return text_part.strip()
            
            print(f"   ⚠️ Token {token_start} non trouvé dans {source_file}")
            return None
            
        except Exception as e:
            print(f"   ❌ Erreur lecture {source_file}: {e}")
            return None
    
    def update_segment(self, segment_id: int, metadata: Dict[str, Any]) -> bool:
        """
        Met à jour un segment avec les nouvelles métadonnées
        """
        try:
            cursor = self.conn.cursor()
            
            # Construire le vecteur TriLDaSA (simplifié - utilise les émotions)
            try:
                vecteur = self.trildasa.generate_vector({
                    "emotion_valence": metadata.get("emotion_valence", 0),
                    "emotion_activation": metadata.get("emotion_activation", 0.5),
                    "tags_roget": metadata.get("tags_roget", [])
                })
            except Exception as e:
                # Fallback: vecteur par défaut basé sur les émotions
                vecteur = {
                    "1": metadata.get("emotion_valence", 0),
                    "2": metadata.get("emotion_activation", 0.5)
                }
            
            cursor.execute("""
                UPDATE metadata SET
                    emotion_valence = ?,
                    emotion_activation = ?,
                    tags_roget = ?,
                    personnes = ?,
                    projets = ?,
                    sujets = ?,
                    resume_texte = ?,
                    gr_id = ?,
                    vecteur_trildasa = ?,
                    confidence_score = ?,
                    date_creation = datetime('now')
                WHERE id = ?
            """, (
                metadata.get("emotion_valence", 0),
                metadata.get("emotion_activation", 0.5),
                str(metadata.get("tags_roget", [])),
                str(metadata.get("personnes", [])),
                str(metadata.get("projets", [])),
                str(metadata.get("sujets", [])),
                metadata.get("resume_texte", ""),
                metadata.get("gr_id", 0),
                str(vecteur),
                metadata.get("confidence_score", 0.5),
                segment_id
            ))
            
            self.conn.commit()
            return True
            
        except Exception as e:
            print(f"   ❌ Erreur UPDATE id={segment_id}: {e}")
            return False
    
    def process_batch(self, segments: List[Dict]) -> Dict[str, int]:
        """
        Traite un batch de segments
        """
        stats = {"success": 0, "failed": 0, "skipped": 0}
        
        # Récupérer les textes
        texts = []
        valid_segments = []
        
        for seg in segments:
            text = self.read_segment_text(seg["source_file"], seg["token_start"], seg["token_end"])
            if text and len(text) > 10:  # Ignorer les textes trop courts
                texts.append(text)
                valid_segments.append(seg)
            else:
                stats["skipped"] += 1
        
        if not texts:
            return stats
        
        if self.dry_run:
            print(f"   🔍 [DRY-RUN] {len(texts)} segments seraient retraités")
            stats["success"] = len(texts)
            return stats
        
        # Appeler Gemini
        try:
            batch_metadata = self.extractor.extract_batch(texts)
            
            for seg, meta in zip(valid_segments, batch_metadata):
                if meta.get("confidence_score", 0.5) > 0.5:
                    if self.update_segment(seg["id"], meta):
                        stats["success"] += 1
                    else:
                        stats["failed"] += 1
                else:
                    stats["failed"] += 1
                    
        except Exception as e:
            print(f"   ❌ Erreur batch Gemini: {e}")
            stats["failed"] += len(valid_segments)
        
        return stats
    
    def run(self, limit: Optional[int] = None, source_filter: Optional[str] = None):
        """
        Lance le rattrapage
        """
        print(f"\n{'='*60}")
        print(f"🔧 SCRIBE RATTRAPAGE v{VERSION}")
        print(f"{'='*60}")
        
        # Récupérer les segments échoués
        segments = self.get_failed_segments(limit=limit, source_filter=source_filter)
        print(f"📊 {len(segments)} segments à rattraper")
        
        if not segments:
            print("✅ Aucun segment à rattraper !")
            return
        
        # Stats globales
        total_stats = {"success": 0, "failed": 0, "skipped": 0}
        start_time = time.time()
        
        # Traiter par batches
        total_batches = (len(segments) + self.batch_size - 1) // self.batch_size
        
        for i in range(0, len(segments), self.batch_size):
            batch = segments[i:i + self.batch_size]
            batch_num = i // self.batch_size + 1
            
            print(f"\n📦 Batch {batch_num}/{total_batches}")
            for seg in batch:
                print(f"   - ID {seg['id']}: {seg['source_file']}")
            
            stats = self.process_batch(batch)
            
            for key in total_stats:
                total_stats[key] += stats[key]
            
            print(f"   ✅ {stats['success']} | ❌ {stats['failed']} | ⏭️ {stats['skipped']}")
            
            # Pause pour éviter rate limiting
            if not self.dry_run and batch_num < total_batches:
                time.sleep(1)
        
        # Résumé
        elapsed = time.time() - start_time
        print(f"\n{'='*60}")
        print(f"✅ TERMINÉ en {elapsed:.1f}s")
        print(f"   ✅ Réussis: {total_stats['success']}")
        print(f"   ❌ Échoués: {total_stats['failed']}")
        print(f"   ⏭️ Skippés: {total_stats['skipped']}")
        print(f"{'='*60}")
        
        # Vérifier combien il en reste
        remaining = self.get_failed_segments()
        print(f"\n📊 Segments restants avec confidence_score = 0.5: {len(remaining)}")


def main():
    parser = argparse.ArgumentParser(description="Rattrapage des segments échoués")
    parser.add_argument("--limit", "-l", type=int, help="Nombre max de segments à traiter")
    parser.add_argument("--all", "-a", action="store_true", help="Traiter tous les segments échoués")
    parser.add_argument("--dry-run", "-n", action="store_true", help="Mode simulation")
    parser.add_argument("--source-file", "-s", type=str, help="Filtrer par nom de fichier source")
    parser.add_argument("--batch-size", "-b", type=int, default=5, help="Taille des batches (défaut: 5)")
    
    args = parser.parse_args()
    
    # Déterminer la limite
    limit = None
    if args.limit:
        limit = args.limit
    elif not args.all:
        limit = 50  # Défaut: 50 segments
        print(f"💡 Utilise --all pour traiter tous les segments, ou --limit N pour un nombre précis")
    
    rattrapage = ScribeRattrapage(dry_run=args.dry_run, batch_size=args.batch_size)
    rattrapage.run(limit=limit, source_filter=args.source_file)


if __name__ == "__main__":
    main()
