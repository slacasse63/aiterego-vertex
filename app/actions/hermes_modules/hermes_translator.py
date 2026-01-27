"""
hermes_translator.py - Traducteur QueryProfile → Masque TriLDaSA

Transforme les poids sémantiques du QueryProfile (générés par Gemini)
en masque de positions numériques compatible avec les vecteurs TriLDaSA.

Architecture:
    QueryProfile (Gemini) → HermesTranslator → Masque {position: poids}
                                                    ↓
                                            Hermès (scoring)

Session de référence: 45_session_trildasa_vecteur_5000.json
"""

import json
import logging
from typing import Dict, Any

logger = logging.getLogger(__name__)


class HermesTranslator:
    """
    Traduit un QueryProfile en masque de pondération TriLDaSA.
    """
    
    # Mapping des clés QueryProfile vers les positions TriLDaSA
    MAPPING = {
        "emotion": [1, 2, 3, 4, 5, 6, 7],        # État interne (valence, activation, stress, etc.)
        "tags_roget": [61, 62, 63, 64, 65, 66],  # Super-classes Roget
    }
    
    # Champs qui restent en SQL (pas dans le vecteur)
    SQL_ONLY_FIELDS = ["timestamp", "personnes", "resume_texte"]
    
    def __init__(self):
        logger.info("HermesTranslator initialisé")
    
    def generate_mask(self, query_profile: Dict[str, Any]) -> Dict[int, float]:
        """
        Génère un masque sparse à partir d'un QueryProfile.
        
        Args:
            query_profile: Dict avec clé "weights" contenant les pondérations
                          Ex: {"weights": {"emotion": 0.5, "tags_roget": 0.3, ...}}
        
        Returns:
            Masque sparse {position: poids, ...}
        """
        mask = {}
        
        # Extraire les weights (gère les deux formats possibles)
        if "weights" in query_profile:
            weights = query_profile["weights"]
        else:
            weights = query_profile
        
        # Construire le masque
        for key, weight in weights.items():
            if key in self.MAPPING and weight > 0:
                for position in self.MAPPING[key]:
                    mask[position] = weight
        
        logger.debug(f"Masque généré: {len(mask)} positions actives")
        return mask
    
    def calculate_resonance(self, segment_vector: Dict, query_mask: Dict[int, float]) -> float:
        """
        Calcule le score de résonance entre un vecteur segment et un masque requête.
        
        Args:
            segment_vector: Vecteur sparse du segment {"1": 0.7, "4": 0.8, ...}
            query_mask: Masque sparse {1: 0.5, 4: 0.5, ...}
        
        Returns:
            Score de résonance (produit scalaire sur positions communes)
        """
        score = 0.0
        
        for pos_str, value in segment_vector.items():
            pos = int(pos_str)
            if pos in query_mask:
                score += value * query_mask[pos]
        
        return round(score, 4)
    
    def extract_sql_filters(self, query_profile: Dict[str, Any]) -> Dict[str, Any]:
        """
        Extrait les filtres qui doivent rester en SQL.
        
        Args:
            query_profile: QueryProfile complet
        
        Returns:
            Dict avec les filtres SQL (date_range_days, personnes, etc.)
        """
        filters = {}
        
        # Filtres explicites
        if "filters" in query_profile:
            filters.update(query_profile["filters"])
        
        # Poids des champs SQL-only (pour pondération hybride)
        weights = query_profile.get("weights", query_profile)
        for field in self.SQL_ONLY_FIELDS:
            if field in weights and weights[field] > 0:
                filters[f"{field}_weight"] = weights[field]
        
        return filters


# === TEST ===
if __name__ == "__main__":
    print("=" * 60)
    print("HERMES TRANSLATOR - Test")
    print("=" * 60)
    
    translator = HermesTranslator()
    
    # Simuler un QueryProfile
    test_profile = {
        "weights": {
            "emotion": 0.5,
            "tags_roget": 0.3,
            "timestamp": 0.15,
            "personnes": 0.05,
            "resume_texte": 0.0
        },
        "filters": {
            "date_range_days": 30,
            "type_contenu": None,
            "domaine": "technique"
        }
    }
    
    print(f"\n📋 QueryProfile: {test_profile['weights']}")
    
    # Générer le masque
    mask = translator.generate_mask(test_profile)
    print(f"\n🎭 Masque TriLDaSA: {mask}")
    
    # Test de résonance avec deux segments
    segment_stresse = {"1": -0.2, "2": 0.6, "4": 0.7, "5": 0.4, "6": 0.7, "7": 0.6, 
                       "61": 1.0, "62": 1.0, "63": 1.0, "64": 1.0, "65": 1.0, "66": 1.0}
    
    segment_calme = {"1": 0.6, "2": 0.7, "5": 0.8, "6": 0.4, "7": 0.3,
                     "61": 1.0, "62": 1.0, "64": 1.0, "65": 1.0, "66": 1.0}
    
    score_stresse = translator.calculate_resonance(segment_stresse, mask)
    score_calme = translator.calculate_resonance(segment_calme, mask)
    
    print(f"\n🔥 Segment stressé (ID 7797): {score_stresse}")
    print(f"😌 Segment calme (ID 7743): {score_calme}")
    
    # Filtres SQL
    sql_filters = translator.extract_sql_filters(test_profile)
    print(f"\n🗃️ Filtres SQL: {sql_filters}")
    
    print("\n" + "=" * 60)
    print("✅ Test terminé!")