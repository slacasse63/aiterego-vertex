"""
Le Scribe v4.2 - Compatible Schema v2.1 (Session 68)

NOUVEAUTÉS v4.2:
- Nettoyage du texte AVANT envoi à Gemini (nettoyer_text.py)
- Encapsulation automatique des blocs [Code] et ```markdown```
- Évite les erreurs JSON causées par code avec caractères spéciaux

HISTORIQUE:
- v4.0 (Session 58-59): Schéma v2, champs épurés, indexable
- v4.1 (Session 61): Blocs thématiques gr_id + confidence_score
- v4.2 (Session 68): Nettoyage texte temps réel (nettoyer_text.py)

CHAMPS SUPPRIMÉS (v4.0):
- cognition_certitude, cognition_complexite, cognition_abstraction
- physique_energie, physique_stress
- comm_clarte, comm_formalite
- type_contenu, organisations, tic, resume_mots_cles, relations
- climat_session, domaine

Usage:
    python -m agents.scribe fichier.txt --gemini -p 15 -b 5
"""

import asyncio
import os
import re
import sqlite3
import json
import time
import tiktoken
import sys
from pathlib import Path
from datetime import datetime, timezone
from dataclasses import dataclass
from typing import List, Tuple, Optional
import httpx

from .extractors import OllamaExtractor, VLLMExtractor, GeminiExtractor

app_dir = Path(__file__).parent.parent
if str(app_dir) not in sys.path:
    sys.path.insert(0, str(app_dir))

from utils.trildasa_engine import TrildasaEngine
from utils.nettoyer_text import nettoyer_segment


# Configuration
BASE_PATH = Path(os.path.expanduser("~/Dropbox/aiterego"))
MEMORY_PATH = Path(os.path.expanduser("~/Dropbox/aiterego_memory"))
ECHANGES_PATH = MEMORY_PATH / "echanges"
INDEX_PATH = BASE_PATH / "index"
ACTIF_PATH = BASE_PATH / "app" / "data"
DB_PATH = MEMORY_PATH / "metadata.db"
TAG_INDEX_PATH = INDEX_PATH / "tag_index_numbered.json"

VALENCE_THRESHOLD = 0.3
ACTIVATION_THRESHOLD = 0.3

# Valeurs par défaut optimisées (stratégie "Essaim")
DEFAULT_BATCH_SIZE = 5
DEFAULT_PARALLEL_BATCHES = 15

ENCODER = tiktoken.get_encoding("cl100k_base")
TIMESTAMP_PATTERN = re.compile(r'\[(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d+Z)\]')

EXTRACTION_MODE = "gemini"
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")

# Configuration vLLM
VLLM_BASE_URL = "http://localhost:8000/v1"
VLLM_MODEL = "mistralai/Mistral-Nemo-Instruct-2407"
VLLM_TIMEOUT = 300.0
VLLM_MAX_RETRIES = 3
VLLM_RETRY_DELAY = 5

# Version du scribe
SCRIBE_VERSION = "4.2"


@dataclass
class Echange:
    timestamp: str
    auteur: str
    texte: str
    token_start: int
    token_count: int = 0  # Nombre de tokens du segment


class Scribe:
    
    def __init__(self, mode: str = EXTRACTION_MODE, parallel_batches: int = 0, batch_size: int = DEFAULT_BATCH_SIZE):
        self.mode = mode
        self.parallel_batches = parallel_batches
        self.batch_size = batch_size
        self.tag_index = self._load_tag_index()
        self.db_conn = None
        self._init_database()
        
        # Initialiser le moteur TriLDaSA
        self.trildasa_engine = TrildasaEngine(str(TAG_INDEX_PATH))
        print(f"🔢 TrildasaEngine initialisé ({self.trildasa_engine.get_stats()['total_tags_mapped']} tags)")
        
        # Stats de session
        self.stats = {
            "indexed": 0,
            "skipped_phatique": 0,
            "candidats_personnes": 0,
            "candidats_projets": 0
        }
        
        if mode == "openai":
            if not OPENAI_API_KEY:
                raise ValueError("OPENAI_API_KEY requis")
            from .extractors import OpenAIExtractor
            self.extractor = OpenAIExtractor(api_key=OPENAI_API_KEY, batch_size=batch_size)
            print(f"🚀 Mode: OpenAI GPT-4o-mini (batch={batch_size})")
        elif mode == "vllm":
            self.extractor = VLLMExtractor(batch_size=batch_size)
            if parallel_batches > 0:
                print(f"⚡ Mode: vLLM PARALLÈLE ({parallel_batches} batches × {batch_size} segments)")
            else:
                print(f"⚡ Mode: vLLM séquentiel (batch={batch_size})")
        elif mode == "gemini":
            self.extractor = GeminiExtractor(batch_size=batch_size)
            print(f"✨ Mode: {self.extractor.model} (batch={batch_size})")
        else:
            self.extractor = OllamaExtractor()
            print(f"🐢 Mode: Ollama local")
    
    def _load_tag_index(self) -> dict:
        with open(TAG_INDEX_PATH, 'r', encoding='utf-8') as f:
            return json.load(f)
    
    def _count_tokens(self, text: str) -> int:
        return len(ENCODER.encode(text))
    
    def _get_db_connection(self) -> sqlite3.Connection:
        if self.db_conn is None:
            self.db_conn = sqlite3.connect(DB_PATH)
        return self.db_conn
    
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
        # Neutraliser les marqueurs inline pour éviter les faux découpages
        text = self._clean_inline_markers(text)
        
        echanges = []
        token_cumule = 0
        
        pattern = re.compile(
            r'\[(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?Z?)\]\s*'
            r'(human|assistant|user|utilisateur|AIter Ego|Human|Assistant|User|Utilisateur|MOSS)\s*:\s*',
            re.IGNORECASE
        )
        
        matches = list(pattern.finditer(text))
        
        if not matches:
            texte = text.strip()
            token_count = self._count_tokens(texte)
            echanges.append(Echange(
                timestamp=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z"),
                auteur="human", 
                texte=texte, 
                token_start=0,
                token_count=token_count
            ))
            return echanges
        
        for i, match in enumerate(matches):
            timestamp = match.group(1)
            auteur_raw = match.group(2).lower()
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
                        token_count=token_count
                    ))
                    token_cumule += token_count
        
        return echanges
    
    def _significant_change(self, prev: dict, curr: dict) -> bool:
        """Détecte un changement significatif entre deux métadonnées."""
        if prev is None:
            return True
        prev_tags = prev.get("tags_roget", [])
        curr_tags = curr.get("tags_roget", [])
        if prev_tags and curr_tags and prev_tags[0] != curr_tags[0]:
            return True
        if abs((curr.get("emotion_valence") or 0) - (prev.get("emotion_valence") or 0)) > VALENCE_THRESHOLD:
            return True
        if abs((curr.get("emotion_activation") or 0.5) - (prev.get("emotion_activation") or 0.5)) > ACTIVATION_THRESHOLD:
            return True
        return False
    
    def _create_fragment_file(self, text: str, timestamp: str) -> Tuple[Path, int]:
        """Crée le fichier fragment tokenisé."""
        lines = []
        cumul = 0
        for line in text.split('\n'):
            line = line.strip()
            if not line:
                continue
            ts_match = TIMESTAMP_PATTERN.match(line)
            lines.append(f"{cumul}|{line}")
            if ts_match:
                content = line[ts_match.end():].strip()
                if content:
                    cumul += self._count_tokens(content)
            else:
                cumul += self._count_tokens(line)
        
        ts_clean = timestamp.replace(':', '-').replace('.', '-')[:19]
        output_dir = ECHANGES_PATH / timestamp[:7].replace('-', '/')
        output_dir.mkdir(parents=True, exist_ok=True)
        output_file = output_dir / f"{ts_clean}.txt"
        
        with open(output_file, 'w', encoding='utf-8') as f:
            f.write('\n'.join(lines))
        return output_file, cumul
    
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
            "resume_mots_cles": json.dumps(metadata.get("sujets", []), ensure_ascii=False),  # sujets remplace resume_mots_cles
            "personnes": json.dumps(metadata.get("personnes", []), ensure_ascii=False),
            "projets": json.dumps(metadata.get("projets", []), ensure_ascii=False),
        }
    
    def _insert_candidat_personne(self, nom: str, segment_id: int, contexte: str = None):
        """Insère un candidat personne pour validation ultérieure."""
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
                         source_file: str, auteur: str, metadata: dict, 
                         source_origine: str) -> Optional[int]:
        """
        Insère les métadonnées dans la base de données (schéma v2.1).
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
            'trace',  # source_nature
            'txt',    # source_format
            source_origine,
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
            f"Iris_{SCRIBE_VERSION}",
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
    
    # =========================================================================
    # MODE TEMPS RÉEL
    # =========================================================================

    def get_insert_fn(self, source_file: str = "realtime", source_origine: str = "gemini_realtime"):
        """
        Retourne une fonction d'insertion compatible avec ScribeQueue.set_db_insert()
        Version schéma v2.1.
        """
        trildasa_engine = self.trildasa_engine
        thread_conn = None
    
        def insert_fn(timestamp: str, token_start: int, auteur: str, metadata: dict):
            nonlocal thread_conn
            
            # === FILTRE INDEXABLE ===
            if metadata.get("indexable") == False:
                return None
            
            if thread_conn is None:
                thread_conn = sqlite3.connect(DB_PATH)
            
            cursor = thread_conn.cursor()
            
            # Estimer token_end (approximatif en temps réel)
            token_end = token_start + 100  # Approximation
            
            # Générer le vecteur TriLDaSA
            row_for_vector = {
                "emotion_valence": metadata.get("emotion_valence", 0.0),
                "emotion_activation": metadata.get("emotion_activation", 0.5),
                "physique_energie": None,
                "physique_stress": None,
                "cognition_certitude": None,
                "cognition_complexite": None,
                "cognition_abstraction": None,
                "comm_clarte": None,
                "comm_formalite": None,
                "lieux": json.dumps(metadata.get("lieux", []), ensure_ascii=False),
                "tags_roget": json.dumps(metadata.get("tags_roget", []), ensure_ascii=False),
                "resume_texte": metadata.get("resume_texte", ""),
                "resume_mots_cles": json.dumps(metadata.get("sujets", []), ensure_ascii=False),
                "personnes": json.dumps(metadata.get("personnes", []), ensure_ascii=False),
                "projets": json.dumps(metadata.get("projets", []), ensure_ascii=False),
            }
            vecteur_trildasa = trildasa_engine.vector_to_json(
                trildasa_engine.generate_vector(row_for_vector)
            )
            
            # timestamp_epoch
            try:
                dt = datetime.fromisoformat(timestamp.replace('Z', '+00:00'))
                timestamp_epoch = int(dt.timestamp())
            except:
                timestamp_epoch = None
            
            # v2.1: gr_id et confidence_score
            gr_id = metadata.get("gr_id")
            confidence_score = metadata.get("confidence_score", 0.5)
            
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
                source_origine,
                auteur,
                metadata.get("emotion_valence", 0.0),
                metadata.get("emotion_activation", 0.5),
                json.dumps(metadata.get("tags_roget", []), ensure_ascii=False),
                json.dumps(metadata.get("personnes", []), ensure_ascii=False),
                json.dumps(metadata.get("projets", []), ensure_ascii=False),
                json.dumps(metadata.get("sujets", []), ensure_ascii=False),
                json.dumps(metadata.get("lieux", []), ensure_ascii=False),
                metadata.get("resume_texte", ""),
                gr_id,  # v2.1
                confidence_score,  # v2.1
                vecteur_trildasa,
                f"Iris_{SCRIBE_VERSION}",
                "gemini-2.5-flash-lite"
            ))
            thread_conn.commit()
            return cursor.lastrowid
        
        return insert_fn
    
    def start_realtime(self, on_processed=None, idle_callback=None):
        """Démarre le Scribe en mode temps réel avec ScribeQueue."""
        from .queue_manager import ScribeQueue
        
        queue = ScribeQueue(
            on_processed=on_processed,
            idle_callback=idle_callback
        )
        queue.set_extractor(self.extractor)
        queue.set_db_insert(self.get_insert_fn())
        queue.start()
        
        print(f"🎙️ Scribe temps réel démarré (mode: {self.mode}, v{SCRIBE_VERSION})")
        return queue

    # =========================================================================
    # PARALLÉLISME ASYNCIO
    # =========================================================================
    
    async def _extract_batch_async(self, texts: List[str], batch_id: int,
                                client: httpx.AsyncClient) -> Tuple[int, List[dict]]:
        if not texts:
            return batch_id, []
        
        # === PATCH GEMINI ===
        if self.mode == "gemini":
            try:
                results = await self.extractor.extract_batch_async(texts)
                return batch_id, results
            except Exception as e:
                print(f"⚠️ Batch {batch_id} Erreur Gemini: {e}")
                return batch_id, [self.extractor.default_metadata() for _ in texts]
        
        texts = [t[:2000] if len(t) > 2000 else t for t in texts]
        prompt = self.extractor._build_batch_prompt(texts)
        
        for attempt in range(VLLM_MAX_RETRIES):
            try:
                response = await client.post(
                    f"{VLLM_BASE_URL}/chat/completions",
                    json={
                        "model": VLLM_MODEL,
                        "messages": [
                            {"role": "system", "content": "Tu es un analyseur de métadonnées expert. Tu retournes UNIQUEMENT du JSON valide, sans texte avant ou après."},
                            {"role": "user", "content": prompt}
                        ],
                        "temperature": 0.1,
                        "max_tokens": 20000
                    }
                )
                response.raise_for_status()
                data = response.json()
                content = data["choices"][0]["message"]["content"]
                results = self.extractor._parse_batch_response(content, len(texts))
                return batch_id, results
                
            except Exception as e:
                print(f"      ⚠️  Batch {batch_id} erreur (tentative {attempt+1}): {e}")
                if attempt < VLLM_MAX_RETRIES - 1:
                    await asyncio.sleep(VLLM_RETRY_DELAY)
                    continue
                else:
                    return batch_id, [self.extractor.default_metadata() for _ in texts]
        
        return batch_id, [self.extractor.default_metadata() for _ in texts]
    
    async def _process_parallel(self, echanges: List[Echange], relative_path: str,
                                 source_origine: str, start_time: float) -> int:
        total_echanges = len(echanges)
        
        batches = []
        batch_echanges_list = []
        for i in range(0, total_echanges, self.batch_size):
            batch = echanges[i:i + self.batch_size]
            # v4.2: Nettoyage + Fix backslash
            batches.append([nettoyer_segment(e.texte).replace('\\', '\\\\') for e in batch])
            batch_echanges_list.append(batch)
        
        total_batches = len(batches)
        print(f"\n  📦 {total_echanges} segments → {total_batches} batches")
        print(f"  ⚡ Parallélisme: {self.parallel_batches} batches simultanés")
        
        all_results = [None] * total_batches
        total_created = 0
        prev_meta, prev_auteur, prev_ts = None, None, None
        prev_group_time = 0
        
        async with httpx.AsyncClient(timeout=VLLM_TIMEOUT) as client:
            for group_start in range(0, total_batches, self.parallel_batches):
                group_end = min(group_start + self.parallel_batches, total_batches)
                group_indices = range(group_start, group_end)
                
                tasks = [
                    self._extract_batch_async(batches[i], i, client)
                    for i in group_indices
                ]
                
                results = await asyncio.gather(*tasks)
                
                for batch_id, batch_results in results:
                    all_results[batch_id] = batch_results
                
                # Indexation immédiate
                group_created = 0
                group_skipped = 0
                for batch_id in group_indices:
                    batch_metadata = all_results[batch_id]
                    batch_ech = batch_echanges_list[batch_id]
                    
                    for echange, metadata in zip(batch_ech, batch_metadata):
                        # Calculer token_end
                        token_end = echange.token_start + echange.token_count
                        
                        should_insert = (prev_meta is None or 
                                       echange.timestamp != prev_ts or 
                                       echange.auteur != prev_auteur or
                                       self._significant_change(prev_meta, metadata))
                        
                        if should_insert:
                            result = self._insert_metadata(
                                echange.timestamp, 
                                echange.token_start,
                                token_end,
                                relative_path, 
                                echange.auteur, 
                                metadata, 
                                source_origine
                            )
                            if result is not None:
                                group_created += 1
                            else:
                                group_skipped += 1
                        
                        prev_meta, prev_auteur, prev_ts = metadata, echange.auteur, echange.timestamp
                
                total_created += group_created
                
                # Affichage avec stats
                elapsed = time.time() - start_time
                delta = elapsed - prev_group_time
                prev_group_time = elapsed
                
                segments_done = min(group_end * self.batch_size, total_echanges)
                pct = (segments_done / total_echanges) * 100
                rate = segments_done / elapsed if elapsed > 0 else 0
                eta = (total_echanges - segments_done) / rate if rate > 0 else 0
                total_estimated = elapsed + eta
                
                elapsed_str = f"{int(elapsed//60):02d}:{int(elapsed%60):02d}"
                delta_str = f"{int(delta//60):02d}:{int(delta%60):02d}"
                eta_str = f"{int(eta//60):02d}:{int(eta%60):02d}"
                total_str = f"{int(total_estimated//60):02d}:{int(total_estimated%60):02d}"
                
                skip_info = f" ({group_skipped} skip)" if group_skipped > 0 else ""
                print(f"  ✓ Batches {group_start+1}-{group_end}/{total_batches} | "
                      f"{pct:.0f}% | {group_created} idx{skip_info} | "
                      f"⏱️ {elapsed_str} (+{delta_str}) | ETA {eta_str} (~{total_str})")
        
        return total_created
    
    # =========================================================================
    # FONCTION PRINCIPALE
    # =========================================================================
    
    def segment_and_index(self, input_file: str = None):
        start_time = time.time()
        
        # Reset stats
        self.stats = {
            "indexed": 0,
            "skipped_phatique": 0,
            "candidats_personnes": 0,
            "candidats_projets": 0
        }
        
        if self.mode == "openai":
            source_origine = "openai_batch"
        elif self.mode == "vllm":
            source_origine = "vllm_valeria"
        elif self.mode == "gemini":
            source_origine = "gemini"
        else:
            source_origine = "local_ollama"
        
        if input_file is None:
            input_path = ACTIF_PATH / "fenetre_active.txt"
        else:
            input_path = Path(input_file)
        
        if not input_path.exists():
            print(f"❌ Fichier non trouvé: {input_path}")
            return None
        
        with open(input_path, 'r', encoding='utf-8') as f:
            raw_text = f.read()
        
        total_tokens = self._count_tokens(raw_text)
        
        print(f"\n{'='*60}")
        print(f"🖋️  LE SCRIBE v{SCRIBE_VERSION} (Schema v2.1) {'(PARALLÈLE)' if self.parallel_batches > 0 else ''}")
        print(f"{'='*60}")
        print(f"📖 {input_path.name}: {len(raw_text):,} chars, {total_tokens:,} tokens")
        
        echanges = self._parse_echanges(raw_text)
        total_echanges = len(echanges)
        total_batches = (total_echanges + self.batch_size - 1) // self.batch_size
        
        print(f"📝 Échanges: {total_echanges} → {total_batches} batches de {self.batch_size}")
        
        if not echanges:
            return None
        
        fragment_path, fragment_tokens = self._create_fragment_file(raw_text, echanges[0].timestamp)
        relative_path = str(fragment_path.relative_to(MEMORY_PATH))
        print(f"✅ Fragment: {relative_path}")
        
        if self.mode in ["vllm", "gemini"] and self.parallel_batches > 0:
            total_created = asyncio.run(
                self._process_parallel(echanges, relative_path, source_origine, start_time)
            )
        else:
            total_created = self._process_sequential(echanges, relative_path, source_origine, start_time)
        
        elapsed = time.time() - start_time
        rate = total_echanges / elapsed if elapsed > 0 else 0
        
        print(f"\n{'='*60}")
        print(f"✅ TERMINÉ en {elapsed:.1f}s ({rate:.1f} segments/sec)")
        print(f"   📊 {self.stats['indexed']} indexés, {self.stats['skipped_phatique']} phatiques skippés")
        if self.stats['candidats_personnes'] > 0 or self.stats['candidats_projets'] > 0:
            print(f"   🆕 Candidats: {self.stats['candidats_personnes']} personnes, {self.stats['candidats_projets']} projets")
        print(f"   🔢 Vecteurs TriLDaSA générés")
        print(f"   🎯 confidence_score + gr_id + nettoyage code (v4.2)")
        print(f"{'='*60}")
        
        return {
            "segments_created": total_created, 
            "segments_skipped": self.stats['skipped_phatique'],
            "echanges_parsed": total_echanges,
            "time_seconds": round(elapsed, 1),
            "rate_per_sec": round(rate, 1),
            "candidats": {
                "personnes": self.stats['candidats_personnes'],
                "projets": self.stats['candidats_projets']
            },
            "mode": f"{self.mode}_p{self.parallel_batches}_b{self.batch_size}" if self.parallel_batches > 0 else self.mode
        }
    
    def _process_sequential(self, echanges: List[Echange], relative_path: str,
                            source_origine: str, start_time: float) -> int:
        total_echanges = len(echanges)
        total_batches = (total_echanges + self.batch_size - 1) // self.batch_size
        
        print(f"\n🔄 Traitement séquentiel...")
        
        total_created = 0
        prev_meta, prev_auteur, prev_ts = None, None, None
        
        # v2.2: Tracker le dernier gr_id utilisé pour continuité inter-batch
        last_gr_id = 0
        
        for batch_num in range(total_batches):
            batch_start = batch_num * self.batch_size
            batch_end = min(batch_start + self.batch_size, total_echanges)
            batch_echanges = echanges[batch_start:batch_end]
            
            elapsed = time.time() - start_time
            pct = (batch_num / total_batches) * 100
            eta = (elapsed / (batch_num + 1)) * (total_batches - batch_num - 1) if batch_num > 0 else 0
            
            print(f"\n   📦 Batch {batch_num + 1}/{total_batches} | {pct:.0f}% | ETA: {int(eta//60):02d}:{int(eta%60):02d}")
            
            # v4.2: Nettoyage + Fix backslash + passage last_gr_id
            batch_texts = [nettoyer_segment(e.texte).replace('\\', '\\\\') for e in batch_echanges]
            
            if self.mode in ["openai", "vllm", "gemini"]:
                batch_metadata = self.extractor.extract_batch(batch_texts, last_gr_id=last_gr_id)
            else:
                batch_metadata = [self.extractor.extract(t) for t in batch_texts]
            
            # v2.2: Mettre à jour last_gr_id avec le max du batch
            for metadata in batch_metadata:
                if metadata.get("indexable", True) and metadata.get("gr_id"):
                    gr_id = metadata.get("gr_id")
                    if isinstance(gr_id, int) and gr_id > last_gr_id:
                        last_gr_id = gr_id
            
            batch_created = 0
            batch_skipped = 0
            for echange, metadata in zip(batch_echanges, batch_metadata):
                token_end = echange.token_start + echange.token_count
                
                should_insert = (prev_meta is None or 
                               echange.timestamp != prev_ts or 
                               echange.auteur != prev_auteur or
                               self._significant_change(prev_meta, metadata))
                
                if should_insert:
                    result = self._insert_metadata(
                        echange.timestamp, 
                        echange.token_start,
                        token_end,
                        relative_path, 
                        echange.auteur, 
                        metadata, 
                        source_origine
                    )
                    if result is not None:
                        batch_created += 1
                    else:
                        batch_skipped += 1
                
                prev_meta, prev_auteur, prev_ts = metadata, echange.auteur, echange.timestamp
            
            total_created += batch_created
            skip_info = f", {batch_skipped} skip" if batch_skipped > 0 else ""
            print(f"      ✅ {batch_created} indexés{skip_info} (total: {total_created}) - last_gr_id: {last_gr_id}")
        
        return total_created


# =============================================================================
# POINT D'ENTRÉE
# =============================================================================

if __name__ == "__main__":
    import sys
    
    mode = EXTRACTION_MODE
    input_file = None
    parallel_batches = 0
    batch_size = DEFAULT_BATCH_SIZE
    realtime = False
    
    args = sys.argv[1:]
    i = 0
    while i < len(args):
        arg = args[i]
        if arg in ["--ollama", "-o"]:
            mode = "ollama"
        elif arg in ["--openai", "-a"]:
            mode = "openai"
        elif arg in ["--gemini", "-g"]:
            mode = "gemini"
        elif arg in ["--vllm", "-v"]:
            mode = "vllm"
        elif arg in ["--realtime", "-r"]:
            realtime = True
        elif arg in ["--parallel", "-p"]:
            if i + 1 < len(args) and args[i + 1].isdigit():
                parallel_batches = int(args[i + 1])
                i += 1
            else:
                parallel_batches = DEFAULT_PARALLEL_BATCHES
        elif arg in ["--batch", "-b"]:
            if i + 1 < len(args) and args[i + 1].isdigit():
                batch_size = int(args[i + 1])
                i += 1
        elif not arg.startswith("-"):
            input_file = arg
        i += 1
    
    if parallel_batches > 0 and mode not in ["vllm", "gemini"]:
        print(f"⚠️  --parallel ignoré (seulement compatible avec --vllm ou --gemini)")
        parallel_batches = 0
    
    scribe = Scribe(mode=mode, parallel_batches=parallel_batches, batch_size=batch_size)
    print(f"📚 Tags: {scribe.tag_index['_meta']['total_tags']}")
    
    if realtime:
        # Mode temps réel interactif
        print("\n" + "="*60)
        print(f"🎙️  SCRIBE MODE TEMPS RÉEL v{SCRIBE_VERSION}")
        print("="*60)
        print("Commandes: 'quit' pour arrêter, 'stats' pour les stats")
        print("Format: timestamp|auteur|texte")
        print("="*60 + "\n")
        
        queue = scribe.start_realtime()
        
        try:
            while True:
                line = input(">> ").strip()
                
                if line.lower() == 'quit':
                    break
                if line.lower() == 'stats':
                    print(f"📊 {queue.stats()}")
                    continue
                if not line:
                    continue
                
                if '|' in line:
                    parts = line.split('|', 2)
                    if len(parts) == 3:
                        ts, auteur, texte = parts
                        queue.put(ts.strip(), auteur.strip(), texte.strip())
                    else:
                        print("⚠️ Format: timestamp|auteur|texte")
                else:
                    from datetime import datetime, timezone
                    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")
                    queue.put(ts, "human", line)
                    
        except KeyboardInterrupt:
            pass
        finally:
            print(f"\n📊 Stats finales: {queue.stats()}")
            queue.stop()
    else:
        # Mode batch classique
        result = scribe.segment_and_index(input_file=input_file)
        if result:
            print(f"\n📊 Résumé: {result}")
