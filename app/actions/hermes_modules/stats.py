"""
hermes_modules/stats.py - Statistiques de la base de métadonnées
"""

from typing import Dict

from actions_config.common_header import get_timestamp
from .db import _get_connection


def get_stats(params: dict = None) -> dict:
    """
    Retourne des statistiques sur la base de métadonnées.
    
    Returns:
        dict avec:
            - status: "success" ou "error"
            - stats: dictionnaire de statistiques
            - timestamp: horodatage UTC
    """
    try:
        conn = _get_connection()
        
        stats = {}
        
        # Nombre total de segments
        stats["total_segments"] = conn.execute("SELECT COUNT(*) FROM metadata").fetchone()[0]
        
        # Plage de dates
        row = conn.execute("SELECT MIN(timestamp), MAX(timestamp) FROM metadata").fetchone()
        stats["date_debut"] = row[0]
        stats["date_fin"] = row[1]
        
        # Distribution par type
        cursor = conn.execute("SELECT type_contenu, COUNT(*) FROM metadata GROUP BY type_contenu")
        stats["par_type"] = {row[0] or "null": row[1] for row in cursor}
        
        # Distribution par domaine
        cursor = conn.execute("SELECT domaine, COUNT(*) FROM metadata GROUP BY domaine")
        stats["par_domaine"] = {row[0] or "null": row[1] for row in cursor}
        
        # Émotion moyenne
        row = conn.execute("SELECT AVG(emotion_valence), AVG(emotion_activation) FROM metadata").fetchone()
        stats["emotion_moyenne"] = {
            "valence": round(row[0] or 0, 3), 
            "activation": round(row[1] or 0, 3)
        }
        
        conn.close()
        
        return {
            "status": "success",
            "stats": stats,
            "timestamp": get_timestamp()
        }
        
    except Exception as e:
        return {
            "status": "error",
            "error": str(e),
            "timestamp": get_timestamp()
        }