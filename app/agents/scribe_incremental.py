"""
scribe_incremental.py - Ajout incrémental de colonnes à metadata.db
MOSS v0.10.4 - Session 70

Permet d'ajouter une nouvelle colonne et d'extraire sa valeur pour tous les segments
existants SANS refaire l'extraction complète des métadonnées.

Usage:
    # Ajouter une colonne avec extraction IA
    python3.11 -m app.agents.scribe_incremental \\
        --field statut_verite \\
        --type INTEGER \\
        --default 0 \\
        --prompt "Évalue si ce segment contient une affirmation factuelle vérifiable..."

    # Ajouter une colonne simple (sans extraction IA)
    python3.11 -m app.agents.scribe_incremental \\
        --field statut_verite \\
        --type INTEGER \\
        --default 0 \\
        --no-extract

    # Mode dry-run
    python3.11 -m app.agents.scribe_incremental --field test --type TEXT --dry-run

    # Limiter le nombre de segments
    python3.11 -m app.agents.scribe_incremental --field test --type TEXT --limit 100

    # Filtrer par source
    python3.11 -m app.agents.scribe_incremental --field test --type TEXT --source chatgpt_prof

Cas d'usage commerciaux:
    - Comptable: facture_id, montant, client
    - Juridique: dossier_ref, confidentialite
    - Santé: patient_id, symptomes
    - RH: employe_id, type_demande
    - MOSS: statut_verite (-1/0/1)
"""

import os
import sys
import json
import sqlite3
import argparse
import time
from pathlib import Path
from typing import Optional, List, Dict, Any, Callable
from dataclasses import dataclass

# Configuration
MEMORY_PATH = Path.home() / "Dropbox" / "aiterego_memory"
ECHANGES_PATH = MEMORY_PATH / "echanges"
DB_PATH = MEMORY_PATH / "metadata.db"

# Version
VERSION = "1.0"

# Types SQL supportés
VALID_SQL_TYPES = ["TEXT", "INTEGER", "REAL", "BLOB"]


@dataclass
class IncrementalConfig:
    """Configuration pour une extraction incrémentale."""
    field_name: str
    field_type: str
    default_value: Any
    extraction_prompt: Optional[str]
    batch_size: int
    dry_run: bool
    limit: Optional[int]
    source_filter: Optional[str]


class IncrementalExtractor:
    """
    Extracteur léger pour un seul champ.
    Utilise Gemini avec un prompt minimaliste et ciblé.
    """
    
    def __init__(self, field_name: str, field_type: str, extraction_prompt: str):
        self.field_name = field_name
        self.field_type = field_type
        self.extraction_prompt = extraction_prompt
        
        # Import Gemini
        try:
            from google import genai
            from google.genai import types
            
            api_key = os.getenv("GEMINI_API_KEY")
            if not api_key:
                raise ValueError("GEMINI_API_KEY non trouvée")
            
            self.client = genai.Client(api_key=api_key)
            self.model = "gemini-2.5-flash-lite"
            self.types = types
            print(f"   ✨ Extracteur Gemini initialisé ({self.model})")
            
        except ImportError:
            raise ImportError("google-genai requis: pip install google-genai")
    
    def _get_config(self):
        """Configuration pour extraction JSON."""
        return self.types.GenerateContentConfig(
            temperature=0.1,  # Très déterministe
            max_output_tokens=256,
            response_mime_type="application/json"
        )
    
    def _build_system_prompt(self) -> str:
        """Construit le prompt système pour l'extraction."""
        type_instruction = {
            "INTEGER": "Retourne un entier (ex: 0, 1, -1, 42)",
            "REAL": "Retourne un nombre décimal (ex: 0.5, 1.0, -0.7)",
            "TEXT": "Retourne une chaîne de caractères",
        }.get(self.field_type, "Retourne la valeur appropriée")
        
        return f"""Tu es un extracteur de métadonnées spécialisé.

TÂCHE: Extraire la valeur du champ "{self.field_name}" pour chaque segment.

INSTRUCTIONS D'EXTRACTION:
{self.extraction_prompt}

TYPE ATTENDU: {self.field_type}
{type_instruction}

RÉPONSE: JSON avec exactement cette structure:
{{"value": <valeur_extraite>}}

Si tu ne peux pas déterminer la valeur, retourne {{"value": null}}
"""
    
    def extract_single(self, text: str) -> Any:
        """Extrait la valeur pour un seul segment."""
        if not text or len(text.strip()) < 3:
            return None
        
        prompt = f"{self._build_system_prompt()}\n\nTEXTE À ANALYSER:\n{text[:2000]}"
        
        try:
            response = self.client.models.generate_content(
                model=self.model,
                contents=prompt,
                config=self._get_config()
            )
            
            if response.text:
                data = json.loads(response.text)
                return data.get("value")
                
        except Exception as e:
            print(f"      ⚠️ Erreur extraction: {e}")
        
        return None
    
    def extract_batch(self, texts: List[str]) -> List[Any]:
        """Extrait les valeurs pour un batch de segments."""
        if not texts:
            return []
        
        # Construire le prompt batch
        segments_text = "\n\n".join([
            f"--- SEGMENT {i+1} ---\n{t[:1500]}"
            for i, t in enumerate(texts)
        ])
        
        batch_prompt = f"""{self._build_system_prompt()}

SEGMENTS À ANALYSER ({len(texts)} segments):
{segments_text}

RÉPONSE: Tableau JSON avec exactement {len(texts)} objets:
[{{"value": <valeur_segment_1>}}, {{"value": <valeur_segment_2>}}, ...]
"""
        
        try:
            response = self.client.models.generate_content(
                model=self.model,
                contents=batch_prompt,
                config=self.types.GenerateContentConfig(
                    temperature=0.1,
                    max_output_tokens=1024,
                    response_mime_type="application/json"
                )
            )
            
            if response.text:
                results = json.loads(response.text)
                if isinstance(results, list):
                    return [r.get("value") for r in results]
                    
        except Exception as e:
            print(f"      ⚠️ Erreur batch: {e}")
        
        return [None] * len(texts)


class ScribeIncremental:
    """
    Scribe Incrémental - Ajoute et remplit une colonne sans refaire l'extraction complète.
    """
    
    def __init__(self, config: IncrementalConfig):
        self.config = config
        self.conn = sqlite3.connect(DB_PATH)
        self.conn.row_factory = sqlite3.Row
        
        # Stats
        self.stats = {
            "total": 0,
            "updated": 0,
            "skipped": 0,
            "errors": 0
        }
        
        # Extracteur (si prompt fourni)
        self.extractor = None
        if config.extraction_prompt:
            self.extractor = IncrementalExtractor(
                config.field_name,
                config.field_type,
                config.extraction_prompt
            )
        
        print(f"\n{'='*60}")
        print(f"🔧 SCRIBE INCRÉMENTAL v{VERSION}")
        print(f"{'='*60}")
        print(f"   Champ: {config.field_name}")
        print(f"   Type: {config.field_type}")
        print(f"   Défaut: {config.default_value}")
        print(f"   Extraction IA: {'Oui' if self.extractor else 'Non'}")
        if config.dry_run:
            print(f"   🔍 MODE DRY-RUN")
    
    def column_exists(self) -> bool:
        """Vérifie si la colonne existe déjà."""
        cursor = self.conn.cursor()
        cursor.execute("PRAGMA table_info(metadata)")
        columns = {col[1] for col in cursor.fetchall()}
        return self.config.field_name in columns
    
    def add_column(self) -> bool:
        """Ajoute la colonne si elle n'existe pas."""
        if self.column_exists():
            print(f"   ℹ️  Colonne '{self.config.field_name}' existe déjà")
            return True
        
        if self.config.dry_run:
            print(f"   🔍 [DRY-RUN] ALTER TABLE metadata ADD COLUMN {self.config.field_name} {self.config.field_type}")
            return True
        
        try:
            cursor = self.conn.cursor()
            
            # Construire la requête ALTER TABLE
            default_clause = ""
            if self.config.default_value is not None:
                if self.config.field_type == "TEXT":
                    default_clause = f" DEFAULT '{self.config.default_value}'"
                else:
                    default_clause = f" DEFAULT {self.config.default_value}"
            
            sql = f"ALTER TABLE metadata ADD COLUMN {self.config.field_name} {self.config.field_type}{default_clause}"
            cursor.execute(sql)
            self.conn.commit()
            
            print(f"   ✅ Colonne '{self.config.field_name}' créée")
            return True
            
        except Exception as e:
            print(f"   ❌ Erreur création colonne: {e}")
            return False
    
    def get_segments_to_update(self) -> List[Dict]:
        """Récupère les segments où le champ est NULL."""
        cursor = self.conn.cursor()
        
        # Construire la requête
        query = f"""
            SELECT id, timestamp, token_start, token_end, source_file
            FROM metadata 
            WHERE {self.config.field_name} IS NULL
        """
        
        if self.config.source_filter:
            query += f" AND source_origine LIKE '%{self.config.source_filter}%'"
        
        query += " ORDER BY timestamp ASC"
        
        if self.config.limit:
            query += f" LIMIT {self.config.limit}"
        
        cursor.execute(query)
        rows = cursor.fetchall()
        
        return [dict(row) for row in rows]
    
    def read_segment_text(self, source_file: str, token_start: int, token_end: int) -> Optional[str]:
        """Lit le texte original d'un segment depuis le fichier source."""
        try:
            # Construire le chemin complet
            file_path = ECHANGES_PATH / source_file
            
            if not file_path.exists():
                return None
            
            with open(file_path, 'r', encoding='utf-8') as f:
                lines = f.readlines()
            
            # Chercher les lignes correspondant aux tokens
            result_lines = []
            for line in lines:
                if '|' in line:
                    parts = line.split('|', 1)
                    if len(parts) == 2:
                        try:
                            line_token = int(parts[0])
                            if token_start <= line_token < token_end:
                                result_lines.append(parts[1].strip())
                        except ValueError:
                            continue
            
            return '\n'.join(result_lines) if result_lines else None
            
        except Exception as e:
            return None
    
    def update_segment(self, segment_id: int, value: Any) -> bool:
        """Met à jour la valeur du champ pour un segment."""
        if self.config.dry_run:
            return True
        
        try:
            cursor = self.conn.cursor()
            
            # Préparer la valeur selon le type
            if value is None:
                sql_value = self.config.default_value
            else:
                sql_value = value
            
            cursor.execute(f"""
                UPDATE metadata 
                SET {self.config.field_name} = ?
                WHERE id = ?
            """, (sql_value, segment_id))
            
            self.conn.commit()
            return True
            
        except Exception as e:
            print(f"      ❌ Erreur UPDATE id={segment_id}: {e}")
            return False
    
    def process_batch(self, segments: List[Dict]) -> Dict[str, int]:
        """Traite un batch de segments."""
        batch_stats = {"updated": 0, "skipped": 0, "errors": 0}
        
        if not self.extractor:
            # Mode sans extraction IA - juste appliquer la valeur par défaut
            for seg in segments:
                if self.update_segment(seg["id"], self.config.default_value):
                    batch_stats["updated"] += 1
                else:
                    batch_stats["errors"] += 1
            return batch_stats
        
        # Mode avec extraction IA
        texts = []
        valid_segments = []
        
        for seg in segments:
            text = self.read_segment_text(
                seg["source_file"],
                seg["token_start"],
                seg["token_end"]
            )
            if text and len(text) > 10:
                texts.append(text)
                valid_segments.append(seg)
            else:
                # Segment illisible - appliquer défaut
                if self.update_segment(seg["id"], self.config.default_value):
                    batch_stats["skipped"] += 1
                else:
                    batch_stats["errors"] += 1
        
        if not texts:
            return batch_stats
        
        # Extraction batch
        values = self.extractor.extract_batch(texts)
        
        for seg, value in zip(valid_segments, values):
            final_value = value if value is not None else self.config.default_value
            if self.update_segment(seg["id"], final_value):
                batch_stats["updated"] += 1
            else:
                batch_stats["errors"] += 1
        
        return batch_stats
    
    def run(self):
        """Lance l'extraction incrémentale."""
        start_time = time.time()
        
        # Étape 1: Créer la colonne si nécessaire
        print(f"\n📋 Étape 1: Vérification/création de la colonne...")
        if not self.add_column():
            print("❌ Abandon - impossible de créer la colonne")
            return
        
        # Étape 2: Récupérer les segments à traiter
        print(f"\n📋 Étape 2: Recherche des segments à mettre à jour...")
        
        # Pour dry-run sans la colonne, simuler
        if self.config.dry_run and not self.column_exists():
            print(f"   🔍 [DRY-RUN] Simulation - tous les segments seraient traités")
            return
        
        segments = self.get_segments_to_update()
        self.stats["total"] = len(segments)
        
        print(f"   📊 {len(segments)} segments à traiter")
        
        if not segments:
            print("   ✅ Aucun segment à mettre à jour!")
            return
        
        # Étape 3: Traitement par batch
        print(f"\n📋 Étape 3: Extraction et mise à jour...")
        
        total_batches = (len(segments) + self.config.batch_size - 1) // self.config.batch_size
        
        for batch_num in range(total_batches):
            batch_start = batch_num * self.config.batch_size
            batch_end = min(batch_start + self.config.batch_size, len(segments))
            batch_segments = segments[batch_start:batch_end]
            
            pct = (batch_num + 1) / total_batches * 100
            print(f"   📦 Batch {batch_num + 1}/{total_batches} ({pct:.0f}%)")
            
            if self.config.dry_run:
                print(f"      🔍 [DRY-RUN] {len(batch_segments)} segments seraient traités")
                self.stats["updated"] += len(batch_segments)
            else:
                batch_stats = self.process_batch(batch_segments)
                self.stats["updated"] += batch_stats["updated"]
                self.stats["skipped"] += batch_stats["skipped"]
                self.stats["errors"] += batch_stats["errors"]
        
        # Bilan final
        elapsed = time.time() - start_time
        print(f"\n{'='*60}")
        print(f"📊 BILAN SCRIBE INCRÉMENTAL")
        print(f"{'='*60}")
        print(f"   Champ: {self.config.field_name}")
        print(f"   Total segments: {self.stats['total']}")
        print(f"   Mis à jour: {self.stats['updated']}")
        print(f"   Ignorés: {self.stats['skipped']}")
        print(f"   Erreurs: {self.stats['errors']}")
        print(f"   Durée: {elapsed:.1f}s")
        
        if self.stats["total"] > 0:
            rate = self.stats["updated"] / self.stats["total"] * 100
            print(f"   Taux de succès: {rate:.1f}%")


def main():
    parser = argparse.ArgumentParser(
        description="Scribe Incrémental - Ajout de colonnes à metadata.db",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Exemples:
  # Ajouter statut_verite (architecture Mnémosyne)
  python3.11 -m app.agents.scribe_incremental \\
      --field statut_verite --type INTEGER --default 0 --no-extract

  # Ajouter un champ avec extraction IA
  python3.11 -m app.agents.scribe_incremental \\
      --field sentiment --type REAL \\
      --prompt "Évalue le sentiment général du segment: -1.0 (très négatif) à +1.0 (très positif)"
        """
    )
    
    parser.add_argument(
        "--field", "-f",
        required=True,
        help="Nom de la nouvelle colonne"
    )
    parser.add_argument(
        "--type", "-t",
        choices=VALID_SQL_TYPES,
        default="TEXT",
        help="Type SQL de la colonne (défaut: TEXT)"
    )
    parser.add_argument(
        "--default", "-d",
        default=None,
        help="Valeur par défaut"
    )
    parser.add_argument(
        "--prompt", "-p",
        default=None,
        help="Prompt d'extraction pour Gemini (si omis, utilise --default sans extraction IA)"
    )
    parser.add_argument(
        "--no-extract",
        action="store_true",
        help="Ne pas utiliser l'extraction IA (juste créer la colonne avec valeur par défaut)"
    )
    parser.add_argument(
        "--batch-size", "-b",
        type=int,
        default=5,
        help="Taille des batches (défaut: 5)"
    )
    parser.add_argument(
        "--dry-run", "-n",
        action="store_true",
        help="Mode simulation"
    )
    parser.add_argument(
        "--limit", "-l",
        type=int,
        default=None,
        help="Limiter le nombre de segments à traiter"
    )
    parser.add_argument(
        "--source", "-s",
        default=None,
        help="Filtrer par source_origine"
    )
    
    args = parser.parse_args()
    
    # Validation
    if args.no_extract and args.prompt:
        print("⚠️  --no-extract et --prompt sont incompatibles")
        return 1
    
    if not args.no_extract and not args.prompt:
        print("⚠️  Spécifiez --prompt pour l'extraction IA ou --no-extract pour créer la colonne sans extraction")
        return 1
    
    # Convertir la valeur par défaut selon le type
    default_value = args.default
    if default_value is not None:
        if args.type == "INTEGER":
            default_value = int(default_value)
        elif args.type == "REAL":
            default_value = float(default_value)
    
    # Configuration
    config = IncrementalConfig(
        field_name=args.field,
        field_type=args.type,
        default_value=default_value,
        extraction_prompt=args.prompt if not args.no_extract else None,
        batch_size=args.batch_size,
        dry_run=args.dry_run,
        limit=args.limit,
        source_filter=args.source
    )
    
    # Exécution
    scribe = ScribeIncremental(config)
    scribe.run()
    
    return 0


if __name__ == "__main__":
    exit(main())
