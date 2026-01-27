"""
hermes_modules/scoring.py - Calculs de score hybride

Contient les fonctions de scoring : proximité Roget, similarité émotionnelle,
et le scoring hybride pondéré.
"""

import json
import math
from datetime import datetime, timezone
from typing import Dict, List, Any, Tuple

from .config import (
    POIDS_ROGET, POIDS_EMOTION, POIDS_TEMPOREL, 
    POIDS_PERSONNES, POIDS_RESUME
)
from .db import _normalize_search
from .hermes_translator import HermesTranslator


def _extract_weights(profile) -> Dict[str, float]:
    """Extrait les poids du QueryProfile."""
    if hasattr(profile, 'weights'):
        return profile.weights
    elif isinstance(profile, dict) and 'weights' in profile:
        return profile['weights']
    else:
        return {
            "tags_roget": POIDS_ROGET,
            "emotion": POIDS_EMOTION,
            "timestamp": POIDS_TEMPOREL,
            "personnes": POIDS_PERSONNES,
            "resume_texte": POIDS_RESUME
        }


def _extract_filters(profile) -> Dict[str, Any]:
    """Extrait les filtres du QueryProfile."""
    if hasattr(profile, 'filters'):
        return profile.filters
    elif isinstance(profile, dict) and 'filters' in profile:
        return profile['filters']
    else:
        return {}


def _extract_strategy(profile) -> Dict[str, Any]:
    """Extrait la stratégie du QueryProfile."""
    if hasattr(profile, 'strategy'):
        return profile.strategy
    elif isinstance(profile, dict) and 'strategy' in profile:
        return profile['strategy']
    else:
        return {"top_k": 5, "include_text_fallback": True}


def _proximite_tags(tag1: str, tag2: str) -> float:
    """
    Calcule la proximité entre deux tags Roget basée sur leur hiérarchie.
    Retourne une valeur entre 0 et 1.
    Format tag: CC-SSSS-TTTT (Classe-Section-Tag)
    """
    try:
        parts1 = tag1.split('-')
        parts2 = tag2.split('-')
        
        if len(parts1) != 3 or len(parts2) != 3:
            return 0.1
        
        classe1, section1, item1 = parts1
        classe2, section2, item2 = parts2
        
        # Classes différentes = très éloignés
        if classe1 != classe2:
            return 0.1
        
        # Même classe, sections différentes
        if section1 != section2:
            distance_section = abs(int(section1) - int(section2))
            return 0.3 + (0.3 * (1 - min(distance_section / 100, 1)))
        
        # Même section, items différents
        distance_item = abs(int(item1) - int(item2))
        return 0.7 + (0.3 * (1 - min(distance_item / 100, 1)))
        
    except (ValueError, IndexError):
        return 0.1


def _similarite_emotion(emotion1: Tuple[float, float], 
                        emotion2: Tuple[float, float]) -> float:
    """
    Calcule la similarité cosinus entre deux vecteurs émotionnels 2D.
    Retourne une valeur entre 0 et 1.
    """
    v1, a1 = emotion1
    v2, a2 = emotion2
    
    # Produit scalaire
    dot = v1 * v2 + a1 * a2
    
    # Normes
    norm1 = math.sqrt(v1**2 + a1**2)
    norm2 = math.sqrt(v2**2 + a2**2)
    
    if norm1 == 0 or norm2 == 0:
        return 0.5  # Neutre si vecteur nul
    
    # Cosinus transformé en [0, 1]
    cosinus = dot / (norm1 * norm2)
    return (cosinus + 1) / 2


# Instance unique du translator (évite de le recréer à chaque segment)
_translator = HermesTranslator()


def _score_candidates(candidats: List[dict], params: dict, weights: Dict[str, float]) -> List[dict]:
    """
    Calcule le score hybride pour chaque candidat.
    Utilise _normalize_search pour comparaison robuste.
    """
    now = datetime.now(timezone.utc)
    
    # Extraire les poids (avec fallback aux défauts)
    poids_roget = weights.get("tags_roget", POIDS_ROGET)
    poids_emotion = weights.get("emotion", POIDS_EMOTION)
    poids_temporel = weights.get("timestamp", POIDS_TEMPOREL)
    poids_personnes = weights.get("personnes", POIDS_PERSONNES)
    poids_resume = weights.get("resume_texte", POIDS_RESUME)
    
    # Générer le masque TriLDaSA une seule fois pour tous les segments
    query_mask = _translator.generate_mask(weights)
    
    for segment in candidats:
        # Score Roget (distance hiérarchique)
        if params.get("tags_explicites") and segment["tags_roget"]:
            score_roget = max(
                _proximite_tags(tag_query, tag_seg)
                for tag_query in params["tags_explicites"]
                for tag_seg in segment["tags_roget"]
            )
        elif segment["tags_roget"]:
            score_roget = 0.5  # Score neutre
        else:
            score_roget = 0.3
        
        # Score émotionnel (similarité cosinus sur 2D)
        if params.get("emotion_cible"):
            score_emotion = _similarite_emotion(
                params["emotion_cible"],
                (segment["emotion_valence"], segment["emotion_activation"])
            )
        else:
            score_emotion = 0.5  # Score neutre
        
        # Score temporel (plus récent = meilleur)
        try:
            seg_time = datetime.fromisoformat(segment["timestamp"].replace('Z', '+00:00'))
            # S'assurer que seg_time est aware
            if seg_time.tzinfo is None:
                seg_time = seg_time.replace(tzinfo=timezone.utc)
            days_ago = (now - seg_time).days
            score_temporel = max(0.1, 1.0 - (days_ago / 365))  # Décroît sur 1 an
        except:
            score_temporel = 0.5
        
        # Score personnes (Normalisé avec la nouvelle fonction)
        score_personnes = 0.5  # Neutre par défaut
        if params.get("personnes") and segment.get("personnes"):
            # On utilise _normalize_search pour comparer (gère accents + JSON)
            personnes_segment_norm = _normalize_search(segment["personnes"])
            
            matches = 0
            for p in params["personnes"]:
                p_norm = _normalize_search(p)
                if p_norm in personnes_segment_norm:
                    matches += 1
            
            if matches > 0:
                score_personnes = min(1.0, 0.5 + (matches * 0.25))
        
        # Score résumé (correspondance textuelle)
        score_resume = 0.5  # Neutre par défaut
        if params.get("mots_cles") and segment.get("resume_texte"):
            resume_lower = segment["resume_texte"].lower()
            matches = sum(1 for mot in params["mots_cles"] if mot in resume_lower)
            if matches > 0:
                score_resume = min(1.0, 0.3 + (matches * 0.15))
        
        # Score TriLDaSA (résonance vectorielle)
        score_trildasa = 0.5  # Neutre par défaut
        if segment.get("vecteur_trildasa"):
            try:
                vecteur = json.loads(segment["vecteur_trildasa"]) if isinstance(segment["vecteur_trildasa"], str) else segment["vecteur_trildasa"]
                raw_score = _translator.calculate_resonance(vecteur, query_mask)
                # Normaliser entre 0 et 1 (score max théorique ~5)
                score_trildasa = min(1.0, raw_score / 5.0)
            except:
                score_trildasa = 0.5
        
        # Score hybride pondéré avec poids dynamiques
        base_score = (
            poids_roget * score_roget +
            poids_emotion * score_emotion +
            poids_temporel * score_temporel +
            poids_personnes * score_personnes +
            poids_resume * score_resume
        )
        
        # Bonus TriLDaSA: amplifie le score de 0% à 20% selon la résonance
        segment["score"] = base_score * (1 + 0.2 * score_trildasa)
        
        # Ajouter les scores détaillés pour debug
        segment["scores_detail"] = {
            "roget": round(score_roget, 3),
            "emotion": round(score_emotion, 3),
            "temporel": round(score_temporel, 3),
            "personnes": round(score_personnes, 3),
            "resume": round(score_resume, 3),
            "trildasa": round(score_trildasa, 3),
            "weights_used": {
                "roget": poids_roget,
                "emotion": poids_emotion,
                "temporel": poids_temporel,
                "personnes": poids_personnes,
                "resume": poids_resume
            }
        }
    
    return candidats