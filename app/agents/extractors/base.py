"""
Interface de base pour les extracteurs de métadonnées.
"""

from abc import ABC, abstractmethod
from typing import List, Dict

class BaseExtractor(ABC):
    """Interface commune pour tous les extracteurs de métadonnées"""
    
    @abstractmethod
    def extract(self, text: str) -> Dict:
        """Extrait les métadonnées d'un seul segment."""
        pass
    
    @abstractmethod
    def extract_batch(self, texts: List[str]) -> List[Dict]:
        """Extrait les métadonnées de plusieurs segments en un seul appel."""
        pass
    
    def default_metadata(self) -> Dict:
        """Retourne des métadonnées par défaut en cas d'erreur"""
        return {
            "tags_roget": ["04-0110-0010"],
            "emotion_valence": 0.0,
            "emotion_activation": 0.5,
            "cognition_certitude": 0.5,
            "cognition_complexite": 0.5,
            "cognition_abstraction": 0.5,
            "physique_energie": None,
            "physique_stress": None,
            "comm_clarte": 0.5,
            "comm_formalite": 0.5,
            "entites": {"personnes": [], "lieux": [], "projets": [], "organisations": []},
            "type_contenu": "information",
            "resume_texte": "",
            "resume_mots_cles": []
        }
