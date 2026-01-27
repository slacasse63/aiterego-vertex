"""
hermes_modules/search_strategies/emotion.py - Recherche par état émotionnel
"""

import json
from typing import Dict

from actions_config.common_header import get_timestamp
from ..db import _get_connection
from ..scoring import _similarite_emotion


def search_by_emotion(params: dict) -> dict:
    """
    Recherche par état émotionnel cible.
    
    Params:
        valence (float): Valeur de valence (-1.0 à 1.0)
        activation (float): Valeur d'activation (0.0 à 1.0)
        top_k (int, optional): Nombre de résultats (défaut: 10)
    
    Returns:
        dict avec status, emotion_cible, resultats, count, timestamp
    """
    valence = params.get("valence", 0.0)
    activation = params.get("activation", 0.5)
    top_k = params.get("top_k", 10)
    
    try:
        conn = _get_connection()
        
        # Récupérer tous les segments avec leurs émotions
        query = """
            SELECT id, timestamp, source_file, token_start, tags_roget,
                   emotion_valence, emotion_activation, type_contenu, domaine,
                   resume_texte, personnes
            FROM metadata
            WHERE emotion_valence IS NOT NULL
            ORDER BY timestamp DESC
            LIMIT 500
        """
        
        cursor = conn.execute(query)
        
        candidats = []
        for row in cursor:
            try:
                tags = json.loads(row['tags_roget']) if row['tags_roget'] else []
            except json.JSONDecodeError:
                tags = []
            
            seg = {
                "id": row['id'],
                "timestamp": row['timestamp'],
                "source_file": row['source_file'],
                "token_start": row['token_start'],
                "tags_roget": tags,
                "emotion_valence": row['emotion_valence'] or 0.0,
                "emotion_activation": row['emotion_activation'] or 0.5,
                "type_contenu": row['type_contenu'] or '',
                "domaine": row['domaine'] or '',
                "resume_texte": row['resume_texte'] or '',
                "personnes": row['personnes'] or '',
                "texte_brut": None
            }
            
            # Calculer le score de similarité émotionnelle
            seg["score"] = _similarite_emotion(
                (valence, activation),
                (seg["emotion_valence"], seg["emotion_activation"])
            )
            
            candidats.append(seg)
        
        conn.close()
        
        # Trier par score et limiter
        candidats.sort(key=lambda x: x["score"], reverse=True)
        resultats = candidats[:top_k]
        
        return {
            "status": "success",
            "emotion_cible": {"valence": valence, "activation": activation},
            "resultats": resultats,
            "count": len(resultats),
            "timestamp": get_timestamp()
        }
        
    except Exception as e:
        return {
            "status": "error",
            "error": str(e),
            "timestamp": get_timestamp()
        }