"""
TrildasaEngine v2.0 — Moteur de vectorisation sémantique AUTO-ALIMENTÉ
Charge automatiquement les mots-clés depuis tag_index_numbered.json

Auteurs: Claude Opus 4.5 + Iris (Gemini 3 Flash Preview) + Serge Music
Date: 2025-12-26
Session: 45

Architecture:
- Positions 1-20:   État Interne (émotions, physique, cognitif) → Cosinus
- Positions 21-40:  Communication (style, ton, clarté) → Réservé v1.1
- Positions 41-60:  Locus & Social (lieu, contexte) → Mots-clés
- Positions 61-66:  Super-Classes Roget (6 classes) → Auto depuis tag_index
- Positions 67-80:  Thèmes Haute Fréquence → Mapping personnalisé
- Positions 81-100: Réservées (ajustement selon usage)
- Positions 201+:   Tags Roget individuels (sparse, optionnel)

Compatibilité:
- schema_metadata.sql (colonnes aplaties)
- QueryProfile (pondération dynamique à la requête)
- Distance hiérarchique Roget (scoring.py)
"""

import json
import logging
from pathlib import Path
from typing import Dict, List, Optional, Any, Set

logger = logging.getLogger(__name__)


class TrildasaEngine:
    """
    Moteur de vectorisation sémantique pour MOSS/AlterEgo.
    
    Auto-alimenté: charge les mots-clés depuis tag_index_numbered.json
    pour construire dynamiquement les dictionnaires de mapping.
    """
    
    # ══════════════════════════════════════════════════════════════════
    # CONFIGURATION DES POSITIONS
    # ══════════════════════════════════════════════════════════════════
    
    # Mapping des colonnes SQL vers les positions du vecteur
    POSITIONS_ETAT_INTERNE = {
        1: "emotion_valence",      # -1 à 1
        2: "emotion_activation",   # 0 à 1
        3: "physique_energie",     # 0 à 1
        4: "physique_stress",      # 0 à 1
        5: "cognition_certitude",  # 0 à 1
        6: "cognition_complexite", # 0 à 1
        7: "cognition_abstraction",# 0 à 1
        # 8-20: Réservées (sommeil, urgence, priorité, capteurs futurs)
    }
    
    POSITIONS_COMMUNICATION = {
        21: "comm_clarte",         # 0 à 1
        22: "comm_formalite",      # 0 à 1
        # 23-40: Réservées
    }
    
    # Mapping des super-classes Roget vers les positions 61-66
    POSITIONS_ROGET_CLASSES = {
        61: "01",  # Relations Abstraites
        62: "02",  # Espace
        63: "03",  # Matière
        64: "04",  # Intellect
        65: "05",  # Volition
        66: "06",  # Affections
    }
    
    # Mapping inverse pour lookup rapide
    ROGET_CLASS_TO_POSITION = {v: k for k, v in POSITIONS_ROGET_CLASSES.items()}
    
    # Positions des thèmes haute fréquence (67-80)
    POSITIONS_THEMES = {
        67: "theme_sante",
        68: "theme_finance",
        69: "theme_tech",
        70: "theme_famille",
        71: "theme_alimentation",
        72: "theme_travail_carriere",
        73: "theme_loisirs",
        74: "theme_education",
        75: "theme_voyage",
        76: "theme_juridique",
        77: "theme_environnement",
        78: "theme_politique",
        # 79-80: Réservées
    }
    
    # Mots-clés pour les thèmes (base, enrichie par l'index)
    THEME_KEYWORDS_BASE = {
        67: ["santé", "médecin", "maladie", "sport", "douleur", "fatigue", "sommeil", 
             "gym", "exercice", "hôpital", "symptôme", "traitement", "health", "doctor"],
        68: ["argent", "facture", "salaire", "achat", "prix", "banque", "paiement", 
             "budget", "économie", "finance", "money", "cost", "payment", "invoice"],
        69: ["code", "programmation", "sql", "python", "api", "bug", "logiciel", 
             "ordi", "tech", "ia", "moss", "algorithm", "software", "database", "server"],
        70: ["famille", "enfant", "parent", "frère", "sœur", "conjoint", "mariage", 
             "bébé", "fils", "fille", "family", "child", "parent", "wife", "husband"],
        71: ["manger", "repas", "cuisine", "restaurant", "recette", "nourriture", 
             "dîner", "déjeuner", "food", "meal", "cook", "eat", "drink"],
        72: ["carrière", "promotion", "emploi", "cv", "entrevue", "patron", "collègue", 
             "projet", "réunion", "deadline", "job", "work", "career", "meeting"],
        73: ["jeu", "musique", "film", "livre", "guitare", "art", "loisir", "détente", 
             "vacances", "hobby", "game", "music", "movie", "book", "relax"],
        74: ["cours", "étude", "université", "examen", "prof", "étudiant", "recherche", 
             "thèse", "diplôme", "school", "study", "university", "student", "exam"],
        75: ["voyage", "avion", "hôtel", "tourisme", "destination", "valise", 
             "passeport", "travel", "trip", "flight", "vacation"],
        76: ["loi", "juridique", "avocat", "procès", "contrat", "droit", "légal",
             "law", "legal", "lawyer", "court", "contract"],
        77: ["environnement", "climat", "écologie", "pollution", "nature", "vert",
             "environment", "climate", "ecology", "green", "sustainable"],
        78: ["politique", "gouvernement", "élection", "parti", "vote", "ministre",
             "politics", "government", "election", "vote", "policy"],
    }
    
    # Mots-clés pour détecter le lieu (positions 41-50)
    LIEU_KEYWORDS = {
        41: ["maison", "home", "appart", "domicile", "chez moi", "chambre", 
             "cuisine", "salon", "appartement", "résidence"],
        42: ["bureau", "office", "travail", "boulot", "entreprise", "réunion",
             "workspace", "job", "company", "meeting room"],
        43: ["voiture", "auto", "bus", "métro", "train", "avion", "transport",
             "car", "subway", "plane", "commute", "trajet"],
        44: ["café", "restaurant", "magasin", "centre", "public", "ville",
             "shop", "store", "mall", "downtown", "city"],
        45: ["parc", "forêt", "montagne", "plage", "nature", "jardin", 
             "extérieur", "park", "forest", "beach", "outdoor"],
        46: ["hôpital", "clinique", "médecin", "dentiste", "pharmacie", 
             "soin", "hospital", "clinic", "doctor", "pharmacy"],
        47: ["seul", "alone", "solo", "solitaire"],
        48: ["famille", "ami", "proche", "ensemble", "family", "friend", "together"],
        49: ["collègue", "client", "professionnel", "colleague", "professional"],
        50: ["foule", "public", "événement", "crowd", "event", "gathering"],
    }
    
    def __init__(self, tag_index_path: Optional[str] = None):
        """
        Initialise le moteur avec chargement automatique de l'index.
        
        Args:
            tag_index_path: Chemin vers tag_index_numbered.json
                           Si None, cherche dans les emplacements par défaut
        """
        self.tag_index: Optional[Dict] = None
        self.roget_keywords: Dict[int, Set[str]] = {}
        self.theme_keywords: Dict[int, Set[str]] = {}
        self.tag_to_position: Dict[str, int] = {}
        
        # Initialiser avec les mots-clés de base
        self._init_base_keywords()
        
        # Charger l'index si disponible
        if tag_index_path:
            self.load_tag_index(tag_index_path)
        else:
            # Chercher dans les emplacements par défaut
            default_paths = [
                "tag_index_numbered.json",
                "app/index/tag_index_numbered.json",
                "../index/tag_index_numbered.json",
                Path(__file__).parent / "tag_index_numbered.json",
                Path(__file__).parent.parent / "index" / "tag_index_numbered.json",
            ]
            for path in default_paths:
                if Path(path).exists():
                    self.load_tag_index(str(path))
                    break
    
    def _init_base_keywords(self):
        """Initialise les dictionnaires avec les mots-clés de base."""
        # Initialiser les positions Roget (61-66) avec des sets vides
        for pos in self.POSITIONS_ROGET_CLASSES.keys():
            self.roget_keywords[pos] = set()
        
        # Initialiser les thèmes avec les mots-clés de base
        for pos, keywords in self.THEME_KEYWORDS_BASE.items():
            self.theme_keywords[pos] = set(kw.lower() for kw in keywords)
    
    def load_tag_index(self, path: str) -> bool:
        """
        Charge le tag_index_numbered.json et construit les dictionnaires.
        
        Args:
            path: Chemin vers le fichier JSON
            
        Returns:
            True si chargement réussi, False sinon
        """
        try:
            with open(path, 'r', encoding='utf-8') as f:
                self.tag_index = json.load(f)
            
            meta = self.tag_index.get('_meta', {})
            logger.info(f"[TrildasaEngine] Index Roget chargé: {meta.get('total_tags', '?')} tags, "
                       f"{meta.get('total_sections', '?')} sections, {meta.get('total_classes', '?')} classes")
            
            # Construire les dictionnaires automatiquement
            self._build_keywords_from_index()
            
            return True
            
        except FileNotFoundError:
            logger.warning(f"[TrildasaEngine] Index non trouvé: {path}")
            return False
        except json.JSONDecodeError as e:
            logger.error(f"[TrildasaEngine] Erreur parsing JSON: {e}")
            return False
        except Exception as e:
            logger.error(f"[TrildasaEngine] Erreur chargement index: {e}")
            return False
    
    def _build_keywords_from_index(self):
        """
        Construit automatiquement les dictionnaires de mots-clés
        à partir du tag_index_numbered.json.
        """
        if not self.tag_index:
            return
        
        classes = self.tag_index.get('classes', {})
        total_keywords = 0
        
        for class_code, class_data in classes.items():
            # Déterminer la position pour cette classe (61-66)
            position = self.ROGET_CLASS_TO_POSITION.get(class_code)
            if position is None:
                continue
            
            # Ajouter les mots-clés de la classe elle-même
            class_keywords = class_data.get('mots_cles', [])
            for kw in class_keywords:
                self.roget_keywords[position].add(kw.lower())
                total_keywords += 1
            
            # Parcourir les sections
            sections = class_data.get('sections', {})
            for section_code, section_data in sections.items():
                # Mots-clés de la section
                section_keywords = section_data.get('mots_cles', [])
                for kw in section_keywords:
                    self.roget_keywords[position].add(kw.lower())
                    total_keywords += 1
                
                # Parcourir les tags
                tags = section_data.get('tags', {})
                for tag_code, tag_data in tags.items():
                    # Construire le code complet CC-SSSS-TTTT
                    full_code = f"{class_code}-{section_code}-{tag_code}"
                    
                    # Mapper le tag vers la position de sa classe
                    self.tag_to_position[full_code] = position
                    
                    # Ajouter les mots-clés du tag
                    tag_keywords = tag_data.get('mots_cles', [])
                    for kw in tag_keywords:
                        kw_lower = kw.lower()
                        self.roget_keywords[position].add(kw_lower)
                        total_keywords += 1
                        
                        # Enrichir aussi les thèmes si pertinent
                        self._enrich_themes_from_keyword(kw_lower, tag_data.get('nom', ''))
        
        logger.info(f"[TrildasaEngine] Dictionnaires construits: {total_keywords} mots-clés, "
                   f"{len(self.tag_to_position)} tags mappés")
    
    def _enrich_themes_from_keyword(self, keyword: str, tag_name: str):
        """
        Enrichit les thèmes haute fréquence avec des mots-clés pertinents
        détectés dans l'index Roget.
        """
        # Mapping de mots-clés spécifiques vers des thèmes
        theme_triggers = {
            67: ["health", "santé", "medical", "medicine", "disease", "illness", 
                 "body", "corps", "pain", "douleur", "healing"],
            68: ["money", "argent", "wealth", "richesse", "payment", "paiement",
                 "commerce", "trade", "property", "propriété", "finance"],
            69: ["computer", "ordinateur", "digital", "numérique", "software",
                 "machine", "technology", "technologie", "code", "algorithm"],
            70: ["family", "famille", "kinship", "parenté", "marriage", "mariage",
                 "child", "enfant", "parent", "domestic"],
            71: ["food", "nourriture", "eating", "manger", "drink", "boire",
                 "nutrition", "meal", "repas", "taste", "goût"],
            72: ["work", "travail", "business", "affaires", "occupation", "métier",
                 "profession", "career", "carrière", "job", "emploi"],
            73: ["play", "jeu", "leisure", "loisir", "amusement", "entertainment",
                 "music", "musique", "art", "recreation", "sport"],
            74: ["education", "éducation", "learning", "apprentissage", "school",
                 "école", "teaching", "enseignement", "study", "étude"],
            75: ["travel", "voyage", "journey", "trajet", "destination", "tourism",
                 "tourisme", "foreign", "étranger"],
        }
        
        keyword_lower = keyword.lower()
        tag_lower = tag_name.lower()
        
        for position, triggers in theme_triggers.items():
            if any(trigger in keyword_lower or trigger in tag_lower for trigger in triggers):
                self.theme_keywords[position].add(keyword_lower)
    
    # ══════════════════════════════════════════════════════════════════
    # GÉNÉRATION DU VECTEUR
    # ══════════════════════════════════════════════════════════════════
    
    def generate_vector(self, row: Dict[str, Any]) -> Dict[int, float]:
        """
        Génère un vecteur sparse à partir d'une ligne de la table metadata.
        
        Args:
            row: Dictionnaire représentant une ligne SQL (colonnes aplaties)
                 Ex: {"emotion_valence": 0.5, "physique_stress": 0.3, ...}
        
        Returns:
            dict: Vecteur sparse {position: valeur, ...}
        """
        vector = {}
        
        # ─────────────────────────────────────────────────────────────
        # 1. ÉTAT INTERNE (Positions 1-20) — Mapping direct
        # ─────────────────────────────────────────────────────────────
        for pos, col_name in self.POSITIONS_ETAT_INTERNE.items():
            val = row.get(col_name)
            if val is not None and val != 0:
                vector[pos] = round(float(val), 3)
        
        # ─────────────────────────────────────────────────────────────
        # 2. COMMUNICATION (Positions 21-40) — Mapping direct
        # ─────────────────────────────────────────────────────────────
        for pos, col_name in self.POSITIONS_COMMUNICATION.items():
            val = row.get(col_name)
            if val is not None and val != 0:
                vector[pos] = round(float(val), 3)
        
        # ─────────────────────────────────────────────────────────────
        # 3. LOCUS & SOCIAL (Positions 41-60) — Détection par mots-clés
        # ─────────────────────────────────────────────────────────────
        lieux_raw = str(row.get("lieux", "") or "").lower()
        
        for pos, keywords in self.LIEU_KEYWORDS.items():
            if any(kw in lieux_raw for kw in keywords):
                vector[pos] = 1.0
        
        # ─────────────────────────────────────────────────────────────
        # 4. SUPER-CLASSES ROGET (Positions 61-66) — Auto depuis index
        # ─────────────────────────────────────────────────────────────
        # Construire le "sac de mots" pour analyse
        bag_of_words = self._build_bag_of_words(row)
        
        for pos, keywords in self.roget_keywords.items():
            if keywords:  # Si on a des mots-clés pour cette position
                score = sum(1 for kw in keywords if kw in bag_of_words)
                if score > 0:
                    # Normalisation adaptative selon la longueur du texte
                    word_count = len(bag_of_words.split())
                    threshold = 1 if word_count < 20 else 3
                    vector[pos] = min(1.0, round(score / threshold, 2))
        
        # ─────────────────────────────────────────────────────────────
        # 5. THÈMES HAUTE FRÉQUENCE (Positions 67-80) — Mots-clés enrichis
        # ─────────────────────────────────────────────────────────────
        for pos, keywords in self.theme_keywords.items():
            if keywords:
                if any(kw in bag_of_words for kw in keywords):
                    vector[pos] = 1.0
        
        # ─────────────────────────────────────────────────────────────
        # 6. TAGS ROGET EXPLICITES (si présents dans les données)
        # ─────────────────────────────────────────────────────────────
        tags_roget = row.get("tags_roget", "")
        if tags_roget:
            self._process_explicit_tags(tags_roget, vector)
        
        return vector
    
    def _build_bag_of_words(self, row: Dict[str, Any]) -> str:
        """Construit un sac de mots à partir des champs textuels."""
        parts = []
        
        # Champs textuels à analyser
        text_fields = ["tags_roget", "resume_texte", "resume_mots_cles", 
                       "personnes", "lieux", "projets", "organisations"]
        
        for field in text_fields:
            val = row.get(field)
            if val:
                parts.append(str(val))
        
        return " ".join(parts).lower()
    
    def _process_explicit_tags(self, tags_str: str, vector: Dict[int, float]):
        """
        Traite les tags Roget explicites (format CC-SSSS-TTTT).
        Active la position de la classe correspondante.
        """
        # Supporter différents formats: "01-0010-0020, 06-0030-0010" ou liste
        if isinstance(tags_str, str):
            tags = [t.strip() for t in tags_str.replace(";", ",").split(",")]
        elif isinstance(tags_str, list):
            tags = tags_str
        else:
            return
        
        for tag in tags:
            tag = tag.strip()
            if not tag:
                continue
            
            # Extraire la classe (2 premiers caractères)
            if len(tag) >= 2:
                class_code = tag[:2]
                position = self.ROGET_CLASS_TO_POSITION.get(class_code)
                if position:
                    # Renforcer la position (max avec existant)
                    current = vector.get(position, 0)
                    vector[position] = max(current, 0.8)
    
    # ══════════════════════════════════════════════════════════════════
    # UTILITAIRES
    # ══════════════════════════════════════════════════════════════════
    
    def vector_to_json(self, vector: Dict[int, float]) -> str:
        """Convertit le vecteur en JSON string pour stockage SQL."""
        return json.dumps(vector, ensure_ascii=False, separators=(',', ':'))
    
    def json_to_vector(self, json_str: str) -> Dict[int, float]:
        """Reconstitue le vecteur depuis le JSON stocké."""
        if not json_str:
            return {}
        try:
            return {int(k): float(v) for k, v in json.loads(json_str).items()}
        except (json.JSONDecodeError, ValueError):
            return {}
    
    def get_stats(self) -> Dict[str, Any]:
        """Retourne des statistiques sur le moteur."""
        return {
            "index_loaded": self.tag_index is not None,
            "total_tags_mapped": len(self.tag_to_position),
            "roget_keywords_count": {pos: len(kws) for pos, kws in self.roget_keywords.items()},
            "theme_keywords_count": {pos: len(kws) for pos, kws in self.theme_keywords.items()},
            "positions_config": {
                "etat_interne": list(self.POSITIONS_ETAT_INTERNE.keys()),
                "communication": list(self.POSITIONS_COMMUNICATION.keys()),
                "roget_classes": list(self.POSITIONS_ROGET_CLASSES.keys()),
                "themes": list(self.POSITIONS_THEMES.keys()),
            }
        }
    
    def describe_vector(self, vector: Dict[int, float]) -> str:
        """Génère une description lisible du vecteur pour debug."""
        descriptions = []
        
        # État interne
        if 1 in vector:
            val = vector[1]
            mood = "positif" if val > 0.3 else "négatif" if val < -0.3 else "neutre"
            descriptions.append(f"Humeur:{mood}({val})")
        if 4 in vector:
            descriptions.append(f"Stress:{vector[4]}")
        
        # Locus
        lieux = []
        lieu_names = {41: "maison", 42: "travail", 43: "transport", 
                      44: "public", 45: "nature", 46: "soin"}
        for pos, name in lieu_names.items():
            if pos in vector:
                lieux.append(name)
        if lieux:
            descriptions.append(f"Lieu:{','.join(lieux)}")
        
        # Super-classes Roget
        classes = []
        class_names = {61: "Abstrait", 62: "Espace", 63: "Matière", 
                       64: "Intellect", 65: "Volition", 66: "Affections"}
        for pos, name in class_names.items():
            if pos in vector:
                classes.append(f"{name}({vector[pos]})")
        if classes:
            descriptions.append(f"Roget:{','.join(classes)}")
        
        # Thèmes
        themes = []
        theme_names = {67: "Santé", 68: "Finance", 69: "Tech", 70: "Famille",
                       71: "Alim", 72: "Travail", 73: "Loisirs", 74: "Éduc", 75: "Voyage"}
        for pos, name in theme_names.items():
            if pos in vector:
                themes.append(name)
        if themes:
            descriptions.append(f"Thèmes:{','.join(themes)}")
        
        return " | ".join(descriptions) if descriptions else "(vecteur vide)"


# ══════════════════════════════════════════════════════════════════════
# SCRIPT DE MIGRATION BATCH
# ══════════════════════════════════════════════════════════════════════

def migrate_database(db_path: str, index_path: str, batch_size: int = 100):
    """
    Migre une base de données existante en ajoutant les vecteurs TRILDASA.
    
    Args:
        db_path: Chemin vers metadata.db
        index_path: Chemin vers tag_index_numbered.json
        batch_size: Nombre de segments par batch
    """
    import sqlite3
    
    print(f"[Migration] Initialisation du moteur...")
    engine = TrildasaEngine(index_path)
    stats = engine.get_stats()
    print(f"[Migration] Moteur prêt: {stats['total_tags_mapped']} tags mappés")
    
    print(f"[Migration] Connexion à {db_path}...")
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    
    # Vérifier/ajouter la colonne vecteur_trildasa
    try:
        cursor.execute("ALTER TABLE metadata ADD COLUMN vecteur_trildasa TEXT")
        print("[Migration] Colonne vecteur_trildasa ajoutée")
    except sqlite3.OperationalError:
        print("[Migration] Colonne vecteur_trildasa existe déjà")
    
    # Compter les segments
    cursor.execute("SELECT COUNT(*) FROM metadata")
    total = cursor.fetchone()[0]
    print(f"[Migration] {total} segments à traiter")
    
    # Traiter par batch
    processed = 0
    cursor.execute("SELECT * FROM metadata")
    
    while True:
        rows = cursor.fetchmany(batch_size)
        if not rows:
            break
        
        for row in rows:
            row_dict = dict(row)
            vector = engine.generate_vector(row_dict)
            vector_json = engine.vector_to_json(vector)
            
            cursor.execute(
                "UPDATE metadata SET vecteur_trildasa = ? WHERE id = ?",
                (vector_json, row_dict['id'])
            )
        
        processed += len(rows)
        pct = (processed / total) * 100
        print(f"[Migration] {processed}/{total} ({pct:.1f}%)")
        conn.commit()
    
    conn.close()
    print(f"[Migration] Terminé! {processed} segments vectorisés")


# ══════════════════════════════════════════════════════════════════════
# EXEMPLE D'UTILISATION
# ══════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    import sys
    
    print("=" * 70)
    print("TRILDASA ENGINE v2.0 — Auto-alimenté par tag_index")
    print("=" * 70)
    
    # Initialiser avec l'index si disponible
    index_path = sys.argv[1] if len(sys.argv) > 1 else None
    engine = TrildasaEngine(index_path)
    
    # Afficher les stats
    stats = engine.get_stats()
    print(f"\n📊 Statistiques du moteur:")
    print(f"   Index chargé: {stats['index_loaded']}")
    print(f"   Tags mappés: {stats['total_tags_mapped']}")
    print(f"   Mots-clés Roget par classe:")
    for pos, count in stats['roget_keywords_count'].items():
        class_name = {61: "Abstrait", 62: "Espace", 63: "Matière", 
                      64: "Intellect", 65: "Volition", 66: "Affections"}.get(pos, f"Pos{pos}")
        print(f"      {class_name} (pos {pos}): {count} mots-clés")
    
    # Test avec un exemple
    print("\n" + "=" * 70)
    print("TEST DE VECTORISATION")
    print("=" * 70)
    
    sample_row = {
        "id": 12345,
        "timestamp": "2025-12-26T10:30:00",
        "emotion_valence": -0.3,
        "emotion_activation": 0.6,
        "physique_stress": 0.7,
        "cognition_certitude": 0.4,
        "comm_clarte": 0.8,
        "lieux": "bureau à domicile",
        "tags_roget": "05-0120-0060, 06-0040-0030",
        "resume_texte": "J'ai payé la facture d'électricité, c'est cher mais nécessaire.",
        "resume_mots_cles": "facture, électricité, paiement, argent",
        "personnes": "",
        "projets": "MOSS"
    }
    
    print(f"\n📥 Entrée (row SQL):")
    for k, v in sample_row.items():
        if v:
            print(f"   {k}: {v}")
    
    vector = engine.generate_vector(sample_row)
    
    print(f"\n📤 Vecteur généré ({len(vector)} positions actives):")
    print(f"   {vector}")
    
    print(f"\n💾 JSON pour stockage:")
    print(f"   {engine.vector_to_json(vector)}")
    
    print(f"\n📝 Description lisible:")
    print(f"   {engine.describe_vector(vector)}")
