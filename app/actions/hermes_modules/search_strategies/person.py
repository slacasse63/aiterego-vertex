"""
hermes_modules/search_strategies/person.py - Recherche par personne
"""

import json
from typing import Dict

from actions_config.common_header import get_timestamp
from ..db import _get_connection, _normalize_search


def search_by_person(params: dict) -> dict:
    """
    Recherche par personne mentionnée.
    
    Params:
        personne (str): Nom de la personne à chercher
        top_k (int, optional): Nombre de résultats (défaut: 10)
    
    Returns:
        dict avec status, personne, resultats, count, timestamp
    """
    personne = params.get("personne", "")
    top_k = params.get("top_k", 10)
    
    if not personne:
        return {
            "status": "error",
            "error": "Paramètre 'personne' manquant",
            "timestamp": get_timestamp()
        }
    
    try:
        conn = _get_connection()
        
        # UTILISATION DE LA FONCTION INJECTÉE
        query = """
            SELECT id, timestamp, source_file, token_start, tags_roget,
                   emotion_valence, emotion_activation, type_contenu, domaine,
                   resume_texte, personnes
            FROM metadata
            WHERE normalize_search(personnes) LIKE ?
            ORDER BY timestamp DESC
            LIMIT ?
        """
        
        normalized_query = f"%{_normalize_search(personne)}%"
        cursor = conn.execute(query, [normalized_query, top_k])
        
        segments = []
        for row in cursor:
            try:
                tags = json.loads(row['tags_roget']) if row['tags_roget'] else []
            except json.JSONDecodeError:
                tags = []
            
            segments.append({
                "id": row['id'],
                "timestamp": row['timestamp'],
                "source_file": row['source_file'],
                "token_start": row['token_start'],
                "tags_roget": tags,
                "emotion_valence": row['emotion_valence'] or 0.0,
                "emotion_activation": row['emotion_activation'] or 0.0,
                "type_contenu": row['type_contenu'] or '',
                "domaine": row['domaine'] or '',
                "resume_texte": row['resume_texte'] or '',
                "personnes": row['personnes'] or '',
                "score": 1.0,
                "texte_brut": None
            })
        
        conn.close()
        
        return {
            "status": "success",
            "personne": personne,
            "resultats": segments,
            "count": len(segments),
            "timestamp": get_timestamp()
        }
        
    except Exception as e:
        return {
            "status": "error",
            "error": str(e),
            "timestamp": get_timestamp()
        }