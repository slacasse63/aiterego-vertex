"""
Le Scribe Rétroactif v2.1 - Compatible Schema v2.1 (Session 61)

Traite les fichiers .txt générés par les parsers (claude_parser.py, chatgpt_parser.py)
et les indexe dans metadata.db avec le GeminiExtractor v2.1.

NOUVEAUTÉS v2.1:
- Support confidence_score (score de confiance Clio)
- Passage du gr_id de Clio à la DB (plus NULL systématique)
- Compatible gemini_extractor v2.1 (Clio v2.1)

HISTORIQUE:
- v2.0 (Session 58-59): Schéma v2, champs épurés, indexable
- v2.1 (Session 61): Blocs thématiques gr_id + confidence_score

Usage:
    python -m agents.scribe_retro exports/chatgpt/ --source chatgpt_prof
    python -m agents.scribe_retro exports/claude/2025-12-16.txt --source claude
    python -m agents.scribe_retro exports/chatgpt/ --source chatgpt_serge --dry-run

Arguments:
    chemin          Fichier .txt ou dossier contenant des .txt
    --source        Identifiant de la source (chatgpt_prof, chatgpt_serge, claude, etc.)
    --dry-run       Afficher ce qui serait fait sans exécuter
    --batch-size    Taille des batches pour GeminiExtractor (défaut: 5)
"""

import os
import re
import json
import sqlite3
import time
import tiktoken
import sys
from datetime import datetime, timezone
from pathlib import Path
from dataclasses import dataclass
from typing import List, Optional, Tuple
import argparse

from .extractors import GeminiExtractor

app_dir = Path(__file__).parent.parent
if str(app_dir) not in sys.path:
    sys.path.insert(0, str(app_dir))

from utils.trildasa_engine import TrildasaEngine

# === CONFIGURATION ===
BASE_PATH = Path(os.path.expanduser("~/Dropbox/aiterego"))
MEMORY_PATH = Path(os.path.expanduser("~/Dropbox/aiterego_memory"))
ECHANGES_PATH = MEMORY_PATH / "echanges"
INDEX_PATH = BASE_PATH / "index"
DB_PATH = MEMORY_PATH / "metadata.db"
TAG_INDEX_PATH = INDEX_PATH / "tag_index_numbered.json"

DEFAULT_BATCH_SIZE = 5
ENCODER = tiktoken.get_encoding("cl100k_base")

# Version
SCRIBE_RETRO_VERSION = "2.1"


@dataclass
class Echange:
    """Un échange individuel (message human ou assistant)"""
    timestamp: str
    auteur: str
    texte: str
    token_start: int
    token_count: int = 0  # Nombre de tokens du segment
    source: str = None


class ScribeRetro:
    """
    Scribe Rétroactif v2.1 - Indexe les exports historiques dans metadata.db (schéma v2.1)
    """
    
    def __init__(self, source_origine: str, batch_size: int = DEFAULT_BATCH_SIZE, dry_run: bool = False):
        self.source_origine = source_origine
        self.batch_size = batch_size
        self.dry_run = dry_run
        self.db_conn = None
        
        # Stats de session
        self.stats = {
            "indexed": 0,
            "skipped_phatique": 0,
            "skipped_duplicate": 0,
            "candidats_personnes": 0,
            "candidats_projets": 0
        }
        
        if not dry_run:
            self.extractor = GeminiExtractor(batch_size=batch_size)
            self._init_database()
            
            # Initialiser le moteur TriLDaSA
            self.trildasa_engine = TrildasaEngine(str(TAG_INDEX_PATH))
            print(f"🔢 TrildasaEngine initialisé ({self.trildasa_engine.get_stats()['total_tags_mapped']} tags)")
        
        print(f"{'🔍 MODE DRY-RUN' if dry_run else f'✨ ScribeRetro v{SCRIBE_RETRO_VERSION} initialisé'}")
        print(f"   Source: {source_origine}")
        print(f"   Batch size: {batch_size}")
    
    def _count_tokens(self, text: str) -> int:
        """Compte les tokens d'un texte"""
        return len(ENCODER.encode(text))
    
    def _get_db_connection(self) -> sqlite3.Connection:
        """Connexion SQLite (lazy)"""
        if self.db_conn is None:
            self.db_conn = sqlite3.connect(DB_PATH)
        return self.db_conn
    
    def _init_database(self):
        """Vérifie que la base v2.1 existe avec les bonnes colonnes."""
        conn = self._get_db_connection()
        cursor = conn.cursor()
        
        # Vérifier les colonnes existantes
        cursor.execute("PRAGMA table_info(metadata)")
        columns = {col[1] for col in cursor.fetchall()}
        
        # v2.1: ajout de confidence_score
        required_columns = {
            'id', 'timestamp', 'timestamp_epoch', 'token_start', 'token_end',
            'source_file', 'source_nature', 'source_format', 'source_origine',
            'auteur', 'emotion_valence', 'emotion_activation', 'tags_roget',
            'personnes', 'projets', 'sujets', 'lieux', 'resume_texte', 'gr_id',
            'pilier', 'vecteur_trildasa', 'poids_mnemique', 'ego_version',
            'modele', 'date_creation', 'confidence_score'  # NOUVEAU v2.1
        }
        
        missing = required_columns - columns
        if missing:
            print(f"⚠️  Colonnes manquantes dans metadata: {missing}")
            print("   Exécutez: ALTER TABLE metadata ADD COLUMN confidence_score REAL;")
        
        # Vérifier les tables candidats
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='projets_candidats'")
        if not cursor.fetchone():
            print("⚠️  Table projets_candidats manquante")
        
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='personnes_candidats'")
        if not cursor.fetchone():
            print("⚠️  Table personnes_candidats manquante")
        
        conn.commit()
        print(f"✅ Base de données vérifiée (schéma v2.1)")
    
    def _clean_inline_markers(self, text: str) -> str:
        """
        Neutralise les marqueurs [SOURCE:] et [timestamp] qui apparaissent
        dans le corps du texte (pas en début de ligne) pour éviter les faux découpages.
        """
        # Remplacer [SOURCE:xxx] qui est PRÉCÉDÉ par un caractère autre que newline
        text = re.sub(r'(?<=[^\n])\[SOURCE:(\w+)\]', r'«SOURCE:\1»', text)
        
        # Remplacer les timestamps inline (précédés par un caractère autre que ] ou newline)
        text = re.sub(
            r'(?<=[^\]\n])\[(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?Z?)\]',
            r'«\1»',
            text
        )
        
        return text
        
    def _parse_echanges(self, text: str) -> List[Echange]:
        # DEBUG: voir les premiers caractères
        
        # Neutraliser les marqueurs inline pour éviter les faux découpages
        text = self._clean_inline_markers(text)
        
        # DEBUG: test manuel du pattern  <-- AJOUTER ICI
        import re
        test_pattern = re.compile(
            r'(?:\[SOURCE:(\w+)\])?\[(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?Z?)\]\s*'
            r'(human|assistant|user|utilisateur|AIter Ego|Human|Assistant|User|Utilisateur|MOSS)\s*:\s*',
            re.IGNORECASE
        )
        test_match = test_pattern.search(text[:300])
        
        echanges = []
        token_cumule = 0
            
        # Pattern pour détecter les échanges
        pattern = re.compile(
            r'(?:\[SOURCE:(\w+)\])?\[(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?Z?)\]\s*'
            r'(human|assistant|user|utilisateur|AIter Ego|Human|Assistant|User|Utilisateur|MOSS)\s*:\s*',
            re.IGNORECASE
        )
        
        matches = list(pattern.finditer(text))
        if not matches:
            # Pas de format reconnu, traiter comme un seul segment
            texte = text.strip()
            token_count = self._count_tokens(texte)
            if texte:
                echanges.append(Echange(
                    timestamp=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z"),
                    auteur="human",
                    texte=texte,
                    token_start=0,
                    token_count=token_count,
                    source=None
                ))
            return echanges
        
        for i, match in enumerate(matches):
            source = match.group(1)  # Peut être None
            timestamp = match.group(2)
            auteur_raw = match.group(3).lower()
            auteur = "human" if auteur_raw in ["human", "user", "utilisateur"] else "assistant"
            
            start_pos = match.end()
            end_pos = matches[i + 1].start() if i + 1 < len(matches) else len(text)
            texte = text[start_pos:end_pos].strip()
            if texte.endswith('['):
                texte = texte[:-1].strip()

            if texte.endswith('[SOURCE:'):
                texte = texte[:-8].strip()
            # Nettoyer les débuts de timestamp orphelins à la fin (ex: "[2025" sans fermeture)
            texte = re.sub(r'\[SOURCE:\w*$', '', texte).strip()  # [SOURCE:chatgpt incomplet
            texte = re.sub(r'\[\d{4}-\d{2}-\d{2}T?\d{0,2}:?\d{0,2}:?\d{0,2}[^\]]*$', '', texte).strip()
            
            if texte:
                if len(texte) < 10 and echanges:
                    # Ajouter au texte du segment précédent
                    echanges[-1].texte += " " + texte
                    echanges[-1].token_count = self._count_tokens(echanges[-1].texte)
                else:
                    token_count = self._count_tokens(texte)
                    echanges.append(Echange(
                        timestamp=timestamp, 
                        auteur=auteur, 
                        texte=texte, 
                        token_start=token_cumule,
                        token_count=token_count, 
                        source=source
                    ))
                    token_cumule += token_count
        
        return echanges
    
    def _create_fragment_file(self, echanges: List[Echange], date_str: str) -> Tuple[Path, str]:
        """
        Crée le fichier fragment tokenisé dans echanges/YYYY/MM/
        Format: token_start|[timestamp] Auteur : texte
        """
        if not echanges:
            raise ValueError("Aucun échange à écrire")
        
        # Déterminer le dossier de sortie
        first_ts = echanges[0].timestamp
        try:
            dt = datetime.fromisoformat(first_ts.replace('Z', '+00:00'))
            output_dir = ECHANGES_PATH / dt.strftime("%Y/%m")
        except:
            output_dir = ECHANGES_PATH / date_str[:7].replace('-', '/')
        
        if not self.dry_run:
            output_dir.mkdir(parents=True, exist_ok=True)
        
        # Nom du fichier basé sur le premier timestamp
        first_ts_clean = first_ts.replace(':', '-').replace('.', '-')[:19]
        output_file = output_dir / f"{first_ts_clean}.txt"
        
        # Construire le contenu tokenisé
        lines = []
        for e in echanges:
            auteur_display = "Utilisateur" if e.auteur == "human" else "AIter Ego"
            source_tag = f"[SOURCE:{e.source}]" if e.source else ""
            line = f"{e.token_start}|{source_tag}[{e.timestamp}] {auteur_display} : {e.texte}"
            lines.append(line)
        
        # Écrire le fichier
        if not self.dry_run:
            with open(output_file, 'w', encoding='utf-8') as f:
                f.write('\n'.join(lines))
        
        relative_path = str(output_file.relative_to(MEMORY_PATH))
        return output_file, relative_path
    
    def _build_row_for_vector(self, metadata: dict) -> dict:
        """Construit le dictionnaire pour la vectorisation TriLDaSA (v2 simplifié)."""
        return {
            "emotion_valence": metadata.get("emotion_valence", 0.0),
            "emotion_activation": metadata.get("emotion_activation", 0.5),
            # Champs supprimés du schéma v2 - on met None
            "physique_energie": None,
            "physique_stress": None,
            "cognition_certitude": None,
            "cognition_complexite": None,
            "cognition_abstraction": None,
            "comm_clarte": None,
            "comm_formalite": None,
            # Champs v2
            "lieux": json.dumps(metadata.get("lieux", []), ensure_ascii=False),
            "tags_roget": json.dumps(metadata.get("tags_roget", []), ensure_ascii=False),
            "resume_texte": metadata.get("resume_texte", ""),
            "resume_mots_cles": json.dumps(metadata.get("sujets", []), ensure_ascii=False),
            "personnes": json.dumps(metadata.get("personnes", []), ensure_ascii=False),
            "projets": json.dumps(metadata.get("projets", []), ensure_ascii=False),
        }
    
    def _insert_candidat_personne(self, nom: str, segment_id: int, contexte: str = None):
        """Insère un candidat personne pour validation ultérieure."""
        if self.dry_run:
            return
        conn = self._get_db_connection()
        cursor = conn.cursor()
        try:
            cursor.execute('''
                INSERT INTO personnes_candidats (nom_detecte, contexte, segment_id)
                VALUES (?, ?, ?)
            ''', (nom, contexte, segment_id))
            conn.commit()
            self.stats["candidats_personnes"] += 1
        except sqlite3.Error as e:
            print(f"⚠️  Erreur insertion candidat personne: {e}")
    
    def _insert_candidat_projet(self, nom: str, segment_id: int, contexte: str = None):
        """Insère un candidat projet pour validation ultérieure."""
        if self.dry_run:
            return
        conn = self._get_db_connection()
        cursor = conn.cursor()
        try:
            cursor.execute('''
                INSERT INTO projets_candidats (nom_detecte, contexte, segment_id)
                VALUES (?, ?, ?)
            ''', (nom, contexte, segment_id))
            conn.commit()
            self.stats["candidats_projets"] += 1
        except sqlite3.Error as e:
            print(f"⚠️  Erreur insertion candidat projet: {e}")
    
    def _insert_metadata(self, timestamp: str, token_start: int, token_end: int,
                         source_file: str, auteur: str, metadata: dict) -> Optional[int]:
        """
        Insère les métadonnées dans SQLite (schéma v2.1).
        Retourne l'ID du segment créé, ou None si skippé.
        """
        # === FILTRE INDEXABLE ===
        if metadata.get("indexable") == False:
            self.stats["skipped_phatique"] += 1
            return None
        
        conn = self._get_db_connection()
        cursor = conn.cursor()
        
        # Générer le vecteur TriLDaSA
        row_for_vector = self._build_row_for_vector(metadata)
        vecteur_trildasa = self.trildasa_engine.vector_to_json(
            self.trildasa_engine.generate_vector(row_for_vector)
        )
        
        # Calculer timestamp_epoch
        try:
            dt = datetime.fromisoformat(timestamp.replace('Z', '+00:00'))
            timestamp_epoch = int(dt.timestamp())
        except:
            timestamp_epoch = None
        
        # Extraire gr_id et confidence_score de Clio (v2.1)
        gr_id = metadata.get("gr_id")  # Peut être None ou int
        confidence_score = metadata.get("confidence_score", 0.5)  # Default 0.5
        
        # === INSERT schéma v2.1 ===
        cursor.execute('''
            INSERT INTO metadata (
                timestamp, timestamp_epoch, token_start, token_end,
                source_file, source_nature, source_format, source_origine,
                auteur, emotion_valence, emotion_activation,
                tags_roget, personnes, projets, sujets, lieux,
                resume_texte, gr_id, confidence_score, vecteur_trildasa,
                ego_version, modele
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
            timestamp,
            timestamp_epoch,
            token_start,
            token_end,
            source_file,
            'trace',
            'txt',
            self.source_origine,
            auteur,
            metadata.get("emotion_valence", 0.0),
            metadata.get("emotion_activation", 0.5),
            json.dumps(metadata.get("tags_roget", []), ensure_ascii=False),
            json.dumps(metadata.get("personnes", []), ensure_ascii=False),
            json.dumps(metadata.get("projets", []), ensure_ascii=False),
            json.dumps(metadata.get("sujets", []), ensure_ascii=False),
            json.dumps(metadata.get("lieux", []), ensure_ascii=False),
            metadata.get("resume_texte", ""),
            gr_id,  # v2.1: gr_id de Clio (peut être None ou int)
            confidence_score,  # v2.1: confidence_score de Clio
            vecteur_trildasa,
            f"Iris_{SCRIBE_RETRO_VERSION}",
            "gemini-2.5-flash-lite"
        ))
        conn.commit()
        segment_id = cursor.lastrowid
        
        # === Gestion des candidats ===
        if metadata.get("personne_candidat"):
            self._insert_candidat_personne(
                metadata["personne_candidat"],
                segment_id,
                metadata.get("resume_texte", "")[:200]
            )
        
        if metadata.get("projet_candidat"):
            self._insert_candidat_projet(
                metadata["projet_candidat"],
                segment_id,
                metadata.get("resume_texte", "")[:200]
            )
        
        self.stats["indexed"] += 1
        return segment_id
    
    def _is_segment_duplicate(self, timestamp: str) -> bool:
        """
        Vérifie si un segment avec ce timestamp exact ET cette source existe déjà.
        
        Discriminants:
        - timestamp: à la microseconde (ex: 2025-12-16T11:41:13.099952Z)
        - source_origine: chatgpt_serge, chatgpt_prof, claude, etc.
        """
        if self.dry_run:
            return False
        
        conn = self._get_db_connection()
        cursor = conn.cursor()
        cursor.execute('''
            SELECT 1 FROM metadata 
            WHERE timestamp = ? AND source_origine = ?
            LIMIT 1
        ''', (timestamp, self.source_origine))
        
        return cursor.fetchone() is not None
    
    def _is_file_already_indexed(self, relative_path: str) -> bool:
        """Vérifie si un fichier a déjà été indexé"""
        if self.dry_run:
            return False
        
        conn = self._get_db_connection()
        cursor = conn.cursor()
        cursor.execute('''
            SELECT 1 FROM metadata 
            WHERE source_file = ? AND source_origine = ?
            LIMIT 1
        ''', (relative_path, self.source_origine))
        
        return cursor.fetchone() is not None
    
    def process_file(self, file_path: Path) -> dict:
        """Traite un fichier .txt et l'indexe dans metadata.db"""
        start_time = time.time()
        
        print(f"\n📄 Traitement: {file_path.name}")
        
        # Lire le fichier
        with open(file_path, 'r', encoding='utf-8') as f:
            content = f.read()
        
        total_tokens = self._count_tokens(content)
        print(f"   📊 {len(content):,} chars, {total_tokens:,} tokens")
        
        # Parser les échanges
        echanges = self._parse_echanges(content)
        if not echanges:
            print(f"   ⚠️ Aucun échange trouvé")
            return {"status": "empty", "echanges": 0}
        
        print(f"   📝 {len(echanges)} échanges détectés")
        
        # Extraire la date du nom de fichier ou du premier timestamp
        date_str = file_path.stem[:10] if len(file_path.stem) >= 10 else echanges[0].timestamp[:10]
        
        # Créer le fichier tokenisé
        fragment_path, relative_path = self._create_fragment_file(echanges, date_str)
        
        # Vérifier si déjà indexé
        if self._is_file_already_indexed(relative_path):
            print(f"   ⏭️  Fichier déjà indexé, skip")
            return {"status": "skipped", "reason": "already_indexed"}
        
        print(f"   ✅ Fragment: {relative_path}")
        
        if self.dry_run:
            print(f"   🔍 [DRY-RUN] {len(echanges)} échanges seraient indexés")
            return {"status": "dry_run", "echanges": len(echanges)}
        
        # Extraire les métadonnées par batch
        total_batches = (len(echanges) + self.batch_size - 1) // self.batch_size
        
        # v2.2: Tracker le dernier gr_id utilisé pour continuité inter-batch
        last_gr_id = 0
        
        for batch_num in range(total_batches):
            batch_start = batch_num * self.batch_size
            batch_end = min(batch_start + self.batch_size, len(echanges))
            batch_echanges = echanges[batch_start:batch_end]
            
            # Extraire les textes
            batch_texts = [e.texte.replace('\\', '\\\\') for e in batch_echanges]
            
            # Appeler GeminiExtractor v2.2 avec last_gr_id pour continuité
            batch_metadata = self.extractor.extract_batch(batch_texts, last_gr_id=last_gr_id)
            
            # v2.2: Mettre à jour last_gr_id avec le max du batch
            for metadata in batch_metadata:
                if metadata.get("indexable", True) and metadata.get("gr_id"):
                    gr_id = metadata.get("gr_id")
                    if isinstance(gr_id, int) and gr_id > last_gr_id:
                        last_gr_id = gr_id
            
            # Insérer dans SQLite (avec vérification doublon)
            for echange, metadata in zip(batch_echanges, batch_metadata):
                if self._is_segment_duplicate(echange.timestamp):
                    self.stats["skipped_duplicate"] += 1
                    continue
                
                # Calculer token_end
                token_end = echange.token_start + echange.token_count
                
                self._insert_metadata(
                    echange.timestamp,
                    echange.token_start,
                    token_end,
                    relative_path,
                    echange.auteur,
                    metadata
                )
            
            # Progress avec last_gr_id pour debug
            pct = (batch_num + 1) / total_batches * 100
            print(f"   📦 Batch {batch_num + 1}/{total_batches} ({pct:.0f}%) - last_gr_id: {last_gr_id}")
        
        elapsed = time.time() - start_time

        
        return {
            "status": "success",
            "echanges": len(echanges),
            "indexed": self.stats["indexed"],
            "skipped_phatique": self.stats["skipped_phatique"],
            "skipped_duplicate": self.stats["skipped_duplicate"],
            "time_seconds": round(elapsed, 1)
        }
    
    def process_directory(self, dir_path: Path) -> dict:
        """Traite tous les fichiers .txt d'un dossier"""
        start_time = time.time()
        
        # Lister les fichiers .txt
        txt_files = sorted(dir_path.glob("*.txt"))
        if not txt_files:
            print(f"❌ Aucun fichier .txt trouvé dans {dir_path}")
            return {"status": "error", "message": "no_files"}
        
        print(f"\n{'='*60}")
        print(f"🖋️  SCRIBE RÉTROACTIF v{SCRIBE_RETRO_VERSION} (Schema v2.1)")
        print(f"{'='*60}")
        print(f"📂 Dossier: {dir_path}")
        print(f"📄 Fichiers: {len(txt_files)}")
        print(f"🏷️  Source: {self.source_origine}")
        print(f"{'='*60}")
        
        results = {
            "files_processed": 0,
            "files_skipped": 0,
            "files_error": 0,
            "total_echanges": 0,
            "total_indexed": 0,
            "total_skipped_phatique": 0,
            "total_skipped_duplicate": 0,
            "candidats_personnes": 0,
            "candidats_projets": 0
        }
        
        for i, txt_file in enumerate(txt_files, 1):
            print(f"\n[{i}/{len(txt_files)}] {txt_file.name}")
            
            # Reset stats pour ce fichier
            self.stats = {
                "indexed": 0,
                "skipped_phatique": 0,
                "skipped_duplicate": 0,
                "candidats_personnes": 0,
                "candidats_projets": 0
            }
            
            try:
                result = self.process_file(txt_file)
                
                if result["status"] == "success":
                    results["files_processed"] += 1
                    results["total_echanges"] += result["echanges"]
                    results["total_indexed"] += self.stats["indexed"]
                    results["total_skipped_phatique"] += self.stats["skipped_phatique"]
                    results["total_skipped_duplicate"] += self.stats["skipped_duplicate"]
                    results["candidats_personnes"] += self.stats["candidats_personnes"]
                    results["candidats_projets"] += self.stats["candidats_projets"]
                elif result["status"] == "skipped":
                    results["files_skipped"] += 1
                elif result["status"] == "dry_run":
                    results["files_processed"] += 1
                    results["total_echanges"] += result["echanges"]
                    
            except Exception as e:
                print(f"   ❌ Erreur: {e}")
                results["files_error"] += 1
        
        elapsed = time.time() - start_time
        
        # Résumé final
        print(f"\n{'='*60}")
        print(f"✅ TERMINÉ en {elapsed:.1f}s")
        print(f"   📄 Fichiers: {results['files_processed']} traités, {results['files_skipped']} skippés, {results['files_error']} erreurs")
        print(f"   📊 Échanges: {results['total_echanges']} parsés")
        print(f"   ✅ Indexés: {results['total_indexed']}")
        if results['total_skipped_phatique'] > 0:
            print(f"   ⏭️  Phatiques skippés: {results['total_skipped_phatique']}")
        if results['total_skipped_duplicate'] > 0:
            print(f"   ⏭️  Doublons skippés: {results['total_skipped_duplicate']}")
        if results['candidats_personnes'] > 0 or results['candidats_projets'] > 0:
            print(f"   🆕 Candidats: {results['candidats_personnes']} personnes, {results['candidats_projets']} projets")
        print(f"   🎯 confidence_score + gr_id inclus (v2.1)")
        print(f"{'='*60}")
        
        results["time_seconds"] = round(elapsed, 1)
        return results


# =============================================================================
# POINT D'ENTRÉE
# =============================================================================

def main():
    parser = argparse.ArgumentParser(
        description="Scribe Rétroactif v2.1 - Indexe les exports ChatGPT/Claude dans metadata.db"
    )
    parser.add_argument(
        "path",
        help="Fichier .txt ou dossier contenant des .txt"
    )
    parser.add_argument(
        "--source", "-s",
        required=True,
        help="Identifiant de la source (chatgpt_prof, chatgpt_serge, claude, etc.)"
    )
    parser.add_argument(
        "--dry-run", "-n",
        action="store_true",
        help="Mode simulation - affiche ce qui serait fait sans exécuter"
    )
    parser.add_argument(
        "--batch-size", "-b",
        type=int,
        default=DEFAULT_BATCH_SIZE,
        help=f"Taille des batches pour GeminiExtractor (défaut: {DEFAULT_BATCH_SIZE})"
    )
    
    args = parser.parse_args()
    
    input_path = Path(args.path).expanduser()
    
    if not input_path.exists():
        print(f"❌ Chemin non trouvé: {input_path}")
        return 1
    
    scribe = ScribeRetro(
        source_origine=args.source,
        batch_size=args.batch_size,
        dry_run=args.dry_run
    )
    
    if input_path.is_file():
        result = scribe.process_file(input_path)
    else:
        result = scribe.process_directory(input_path)
    
    print(f"\n📊 Résultat: {result}")
    return 0


if __name__ == "__main__":
    exit(main())
