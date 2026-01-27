"""
hermes_modules/search_strategies/date.py - Recherche par plage de dates
"""

import json
from datetime import datetime, timezone
from typing import Dict

from actions_config.common_header import get_timestamp
from ..db import _get_connection


def search_by_date(params: dict) -> dict:
    """
    Recherche par plage de dates.
    
    Params:
        debut (str): Date de début (format ISO)
        fin (str): Date de fin (format ISO)
        top_k (int, optional): Nombre de résultats (défaut: 20)
    
    Returns:
        dict avec status, periode, resultats, count, timestamp
    """
    debut = params.get("debut")
    fin = params.get("fin")
    top_k = params.get("top_k", 20)
    
    if not debut or not fin:
        return {
            "status": "error",
            "error": "Paramètres 'debut' et 'fin' requis",
            "timestamp": get_timestamp()
        }
    
    try:
        conn = _get_connection()
        
        # Normaliser les dates en UTC
        date_debut = datetime.fromisoformat(debut).replace(tzinfo=timezone.utc)
        date_fin = datetime.fromisoformat(fin).replace(tzinfo=timezone.utc)
        
        query = """
            SELECT id, timestamp, source_file, token_start, tags_roget,
                   emotion_valence, emotion_activation, type_contenu, domaine,
                   resume_texte, personnes
            FROM metadata
            WHERE timestamp >= ? AND timestamp <= ?
            ORDER BY timestamp DESC
            LIMIT ?
        """
        
        cursor = conn.execute(query, [date_debut.isoformat(), date_fin.isoformat(), top_k])
        
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
            "periode": {"debut": debut, "fin": fin},
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