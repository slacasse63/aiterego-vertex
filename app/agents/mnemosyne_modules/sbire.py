"""
sbire.py - Exécutant Python pour Mnémosyne
MOSS v0.11.0 - Session 72

Le Sbire est le "bras" de Mnémosyne. Il exécute les mandats de recherche
sans utiliser de tokens IA (100% Python).

Responsabilités:
    - GREP dans les fichiers tokenisés
    - Recherche SQL dans metadata.db
    - Expansion Word2Vec (si gensim disponible)
    - Écriture: statut_verite, edges, piliers

Principe: Mnémosyne réfléchit, le Sbire exécute.
"""

import re
import json
import sqlite3
from pathlib import Path
from typing import List, Dict, Optional, Any
from dataclasses import dataclass


@dataclass
class Mandat:
    """Un mandat de recherche généré par Mnémosyne."""
    type: str  # 'grep', 'sql', 'word2vec'
    pattern: Optional[str] = None
    query: Optional[str] = None
    context: str = ""
    iteration: int = 1
    max_results: int = 50


class Sbire:
    """
    Le Sbire - Exécutant Python pour Mnémosyne.
    
    Fait le travail de scan et d'écriture sans coûter de tokens.
    Toutes les opérations sont 100% déterministes.
    """
    
    def __init__(self, db_path: Path, echanges_path: Path, verbose: bool = False):
        """
        Initialise le Sbire.
        
        Args:
            db_path: Chemin vers metadata.db
            echanges_path: Chemin vers le dossier des échanges tokenisés
            verbose: Afficher les détails d'exécution
        """
        self.db_path = db_path
        self.echanges_path = echanges_path
        self.verbose = verbose
        self._conn = None
        
        # Statistiques
        self.stats = {
            "grep_executes": 0,
            "sql_executes": 0,
            "word2vec_executes": 0,
            "updates_statut": 0,
            "inserts_edge": 0,
            "inserts_pilier": 0,
            "inserts_segment": 0
        }
    
    # =========================================================================
    # CONNEXION BASE DE DONNÉES
    # =========================================================================
    
    def _get_db(self) -> sqlite3.Connection:
        """Connexion lazy à la base de données."""
        if self._conn is None:
            self._conn = sqlite3.connect(self.db_path)
            self._conn.row_factory = sqlite3.Row
        return self._conn
    
    def close(self):
        """Ferme la connexion à la base."""
        if self._conn:
            self._conn.close()
            self._conn = None
    
    # =========================================================================
    # EXÉCUTION DES MANDATS
    # =========================================================================
    
    def execute(self, mandat: Mandat) -> List[Dict]:
        """
        Exécute un mandat de recherche.
        
        Args:
            mandat: Le mandat généré par Mnémosyne
            
        Returns:
            Liste de résultats bruts
        """
        if self.verbose:
            print(f"      🔧 Sbire: {mandat.type} (iter {mandat.iteration})")
        
        if mandat.type == 'grep':
            return self.grep_files(mandat.pattern, mandat.max_results)
        elif mandat.type == 'sql':
            return self.search_sql(mandat.query, mandat.max_results)
        elif mandat.type == 'word2vec':
            return self.search_word2vec(mandat.query, mandat.max_results)
        else:
            if self.verbose:
                print(f"      ⚠️ Type de mandat inconnu: {mandat.type}")
            return []
    
    # =========================================================================
    # GREP - Recherche dans les fichiers
    # =========================================================================
    
    def grep_files(self, pattern: str, max_results: int = 50) -> List[Dict]:
        """
        Recherche par pattern regex dans les fichiers tokenisés.
        
        Args:
            pattern: Expression régulière à chercher
            max_results: Nombre maximum de résultats
            
        Returns:
            Liste de correspondances avec fichier, ligne, contenu
        """
        self.stats["grep_executes"] += 1
        results = []
        
        try:
            regex = re.compile(pattern, re.IGNORECASE)
        except re.error as e:
            if self.verbose:
                print(f"      ⚠️ Pattern regex invalide: {e}")
            return []
        
        # Parcourir les fichiers (du plus récent au plus ancien)
        for year_month in sorted(self.echanges_path.iterdir(), reverse=True):
            if not year_month.is_dir():
                continue
                
            for day_dir in sorted(year_month.iterdir(), reverse=True):
                if not day_dir.is_dir():
                    continue
                    
                for txt_file in sorted(day_dir.glob("*.txt"), reverse=True):
                    try:
                        content = txt_file.read_text(encoding='utf-8')
                        
                        for line_num, line in enumerate(content.split('\n'), 1):
                            match = regex.search(line)
                            if match:
                                # Extraire le token de début si présent
                                token_start = None
                                if '|' in line:
                                    try:
                                        token_start = int(line.split('|')[0])
                                    except ValueError:
                                        pass
                                
                                results.append({
                                    'file': str(txt_file.relative_to(self.echanges_path)),
                                    'line_num': line_num,
                                    'token_start': token_start,
                                    'content': line[:500],
                                    'match': match.group(0)
                                })
                                
                                if len(results) >= max_results:
                                    return results
                                    
                    except Exception as e:
                        if self.verbose:
                            print(f"      ⚠️ Erreur lecture {txt_file}: {e}")
                        continue
        
        return results
    
    # =========================================================================
    # SQL - Recherche dans metadata.db
    # =========================================================================
    
    def search_sql(self, query: str, max_results: int = 50) -> List[Dict]:
        """
        Recherche dans metadata.db par mots-clés.
        
        Args:
            query: Mots-clés à chercher
            max_results: Nombre maximum de résultats
            
        Returns:
            Liste de segments correspondants
        """
        self.stats["sql_executes"] += 1
        conn = self._get_db()
        cursor = conn.cursor()
        
        try:
            # Recherche dans plusieurs champs
            cursor.execute("""
                SELECT id, timestamp, source_file, resume_texte, 
                       personnes, projets, sujets, statut_verite, 
                       confidence_score, token_start, token_end
                FROM metadata
                WHERE resume_texte LIKE ? 
                   OR sujets LIKE ?
                   OR personnes LIKE ?
                   OR projets LIKE ?
                ORDER BY timestamp DESC
                LIMIT ?
            """, (f"%{query}%", f"%{query}%", f"%{query}%", f"%{query}%", max_results))
            
            results = []
            for row in cursor.fetchall():
                results.append(dict(row))
            
            return results
            
        except Exception as e:
            if self.verbose:
                print(f"      ⚠️ Erreur SQL: {e}")
            return []
    
    def search_sql_by_ids(self, ids: List[int]) -> List[Dict]:
        """
        Récupère des segments par leurs IDs.
        
        Args:
            ids: Liste d'IDs de segments
            
        Returns:
            Liste de segments
        """
        if not ids:
            return []
            
        conn = self._get_db()
        cursor = conn.cursor()
        
        try:
            placeholders = ','.join('?' * len(ids))
            cursor.execute(f"""
                SELECT id, timestamp, source_file, resume_texte, 
                       personnes, projets, sujets, statut_verite,
                       confidence_score, token_start, token_end
                FROM metadata
                WHERE id IN ({placeholders})
            """, ids)
            
            return [dict(row) for row in cursor.fetchall()]
            
        except Exception as e:
            if self.verbose:
                print(f"      ⚠️ Erreur SQL by IDs: {e}")
            return []
    
    # =========================================================================
    # WORD2VEC - Expansion sémantique
    # =========================================================================
    
    def search_word2vec(self, query: str, max_results: int = 50) -> List[Dict]:
        """
        Recherche avec expansion Word2Vec des termes.
        
        Args:
            query: Terme à chercher et expandre
            max_results: Nombre maximum de résultats
            
        Returns:
            Liste de segments correspondants (dédupliqués)
        """
        self.stats["word2vec_executes"] += 1
        
        # Chemin du modèle
        models_path = self.echanges_path.parent / "models"
        model_path = models_path / "clusters.model"
        
        if not model_path.exists():
            if self.verbose:
                print(f"      ⚠️ Modèle Word2Vec non trouvé: {model_path}")
            # Fallback sur SQL simple
            return self.search_sql(query, max_results)
        
        try:
            from gensim.models import Word2Vec
            model = Word2Vec.load(str(model_path))
            
            # Trouver les termes similaires
            query_lower = query.lower().replace(' ', '_')
            
            try:
                similar = model.wv.most_similar(query_lower, topn=10)
                expanded_terms = [query] + [term.replace('_', ' ') for term, score in similar if score > 0.5]
            except KeyError:
                # Terme pas dans le vocabulaire
                expanded_terms = [query]
            
            if self.verbose:
                print(f"      📊 Expansion: {query} → {expanded_terms[:5]}")
            
            # Rechercher avec les termes expandus
            all_results = []
            seen_ids = set()
            
            for term in expanded_terms[:5]:  # Limiter à 5 termes
                results = self.search_sql(term, max_results // 2)
                for r in results:
                    if r['id'] not in seen_ids:
                        seen_ids.add(r['id'])
                        all_results.append(r)
                        
                        if len(all_results) >= max_results:
                            return all_results
            
            return all_results
            
        except ImportError:
            if self.verbose:
                print("      ⚠️ gensim non installé - fallback SQL")
            return self.search_sql(query, max_results)
            
        except Exception as e:
            if self.verbose:
                print(f"      ⚠️ Erreur Word2Vec: {e}")
            return self.search_sql(query, max_results)
    
    # =========================================================================
    # ÉCRITURE - Modifications base de données
    # =========================================================================
    
    def update_statut_verite(self, segment_id: int, statut: int) -> bool:
        """
        Met à jour le statut_verite d'un segment.
        
        Args:
            segment_id: ID du segment
            statut: -1 (réfuté), 0 (neutre), 1 (validé)
            
        Returns:
            True si mise à jour réussie
        """
        conn = self._get_db()
        cursor = conn.cursor()
        
        try:
            cursor.execute(
                "UPDATE metadata SET statut_verite = ? WHERE id = ?",
                (statut, segment_id)
            )
            conn.commit()
            
            if cursor.rowcount > 0:
                self.stats["updates_statut"] += 1
                return True
            return False
            
        except Exception as e:
            if self.verbose:
                print(f"      ❌ Erreur UPDATE statut_verite: {e}")
            return False
    
    def insert_edge(self, source_id: int, target_id: int, 
                    edge_type: str, metadata: Dict = None, 
                    poids: float = 1.0) -> bool:
        """
        Insère un lien dans la table edges.
        
        Args:
            source_id: ID du segment source
            target_id: ID du segment cible
            edge_type: Type de lien (CORRIGE_PAR, TRAJECTOIRE, etc.)
            metadata: Métadonnées JSON optionnelles
            poids: Poids du lien (défaut: 1.0)
            
        Returns:
            True si insertion réussie
        """
        conn = self._get_db()
        cursor = conn.cursor()
        
        try:
            cursor.execute("""
                INSERT INTO edges (source_id, target_id, type, metadata, poids)
                VALUES (?, ?, ?, ?, ?)
            """, (
                source_id, 
                target_id, 
                edge_type, 
                json.dumps(metadata or {}, ensure_ascii=False),
                poids
            ))
            conn.commit()
            
            self.stats["inserts_edge"] += 1
            return True
            
        except Exception as e:
            if self.verbose:
                print(f"      ❌ Erreur INSERT edge: {e}")
            return False
    
    def insert_pilier(self, fait: str, categorie: str = "FAIT", 
                      importance: int = 2, source_id: int = None) -> Optional[int]:
        """
        Insère un nouveau pilier.
        
        Args:
            fait: Le fait à consolider
            categorie: IDENTITE, RECHERCHE, TECHNIQUE, RELATION, VALEUR, FAIT
            importance: 0-3
            source_id: ID du segment source (optionnel)
            
        Returns:
            ID du pilier créé, ou None si échec
        """
        conn = self._get_db()
        cursor = conn.cursor()
        
        try:
            cursor.execute("""
                INSERT INTO piliers (fait, categorie, importance, source_id)
                VALUES (?, ?, ?, ?)
            """, (fait, categorie.upper(), importance, source_id))
            conn.commit()
            
            self.stats["inserts_pilier"] += 1
            return cursor.lastrowid
            
        except Exception as e:
            if self.verbose:
                print(f"      ❌ Erreur INSERT pilier: {e}")
            return None
    
    def insert_segment_internal(self, resume: str, source: str = "mnemosyne",
                                auteur: str = "iris_internal") -> Optional[int]:
        """
        Insère un segment interne (pour l'injection vers Iris).
        
        Args:
            resume: Texte du segment
            source: Source du segment
            auteur: Auteur (iris_internal pour la boucle de conscience)
            
        Returns:
            ID du segment créé, ou None si échec
        """
        conn = self._get_db()
        cursor = conn.cursor()
        
        from datetime import datetime
        now = datetime.now()
        timestamp = now.isoformat()
        timestamp_epoch = int(now.timestamp())
        
        try:
            cursor.execute("""
                INSERT INTO metadata (
                    timestamp, timestamp_epoch, token_start, token_end,
                    source_file, source_nature, source_format, source_origine,
                    auteur, resume_texte, statut_verite, confidence_score, date_creation
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                timestamp,
                timestamp_epoch,
                0,  # token_start (pas applicable pour segments internes)
                0,  # token_end (pas applicable pour segments internes)
                f"internal/{source}",
                "reflexion",
                "internal",
                source,
                auteur,
                resume,
                1,  # statut_verite = 1 (validé)
                1.0,  # confidence_score
                timestamp
            ))
            conn.commit()
            
            self.stats["inserts_segment"] += 1
            return cursor.lastrowid
            
        except Exception as e:
            if self.verbose:
                print(f"      ❌ Erreur INSERT segment: {e}")
            return None
    
    # =========================================================================
    # UTILITAIRES
    # =========================================================================
    
    def get_stats(self) -> Dict[str, int]:
        """Retourne les statistiques d'exécution."""
        return self.stats.copy()
    
    def check_segment_exists(self, segment_id: int) -> bool:
        """Vérifie si un segment existe."""
        conn = self._get_db()
        cursor = conn.cursor()
        
        try:
            cursor.execute("SELECT 1 FROM metadata WHERE id = ?", (segment_id,))
            return cursor.fetchone() is not None
        except:
            return False
    
    def get_piliers_by_category(self, categorie: str = None) -> List[Dict]:
        """Récupère les piliers, optionnellement par catégorie."""
        conn = self._get_db()
        cursor = conn.cursor()
        
        try:
            if categorie:
                cursor.execute(
                    "SELECT * FROM piliers WHERE categorie = ? ORDER BY importance DESC",
                    (categorie.upper(),)
                )
            else:
                cursor.execute("SELECT * FROM piliers ORDER BY importance DESC")
            
            return [dict(row) for row in cursor.fetchall()]
            
        except Exception as e:
            if self.verbose:
                print(f"      ⚠️ Erreur lecture piliers: {e}")
            return []
