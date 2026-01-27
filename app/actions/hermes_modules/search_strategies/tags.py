"""
hermes_modules/search_strategies/tags.py - Recherche par tags Roget
"""

from typing import Dict

from actions_config.common_header import get_timestamp


def search_by_tags(params: dict) -> dict:
    """
    Recherche directe par tags Roget.
    
    Params:
        tags (list): Liste de tags au format XX-XXXX-XXXX
        top_k (int, optional): Nombre de résultats (défaut: 10)
    
    Returns:
        dict avec status, resultats, count, timestamp
    
    Note:
        Cette fonction délègue à la recherche principale run()
        avec les tags comme requête.
    """
    tags = params.get("tags", [])
    top_k = params.get("top_k", 10)
    
    if not tags:
        return {
            "status": "error",
            "error": "Paramètre 'tags' manquant ou vide",
            "timestamp": get_timestamp()
        }
    
    # Import local pour éviter les imports circulaires
    from ..core import run
    
    return run({
        "query": " ".join(tags),
        "top_k": top_k
    })