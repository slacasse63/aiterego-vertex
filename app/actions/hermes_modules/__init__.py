"""
hermes_modules/__init__.py - Exports du module Hermès

Ce module expose toutes les fonctions et constantes nécessaires
pour la façade hermes.py
"""

# === CONSTANTES ===
from .config import (
    DB_PATH,
    TEXTE_BASE_PATH,
    POIDS_ROGET,
    POIDS_EMOTION,
    POIDS_TEMPOREL,
    POIDS_PERSONNES,
    POIDS_RESUME,
    DEFAULT_TOP_K,
    MAX_TOKENS_CONTEXT
)

try:
    from .clusters import expand_query
except ImportError:
    pass

# === FONCTIONS DB ===
from .db import (
    _get_connection,
    _normalize_search
)

# === PARSING ===
from .parsing import (
    _parse_query,
    STOPWORDS
)

# === SCORING ===
from .scoring import (
    _score_candidates,
    _proximite_tags,
    _similarite_emotion,
    _extract_weights,
    _extract_filters,
    _extract_strategy
)

# === CORE ===
from .core import (
    run,
    _search_metadata,
    _load_texte_brut,
    _format_context
)

# === STATS ===
from .stats import get_stats

# === SEARCH STRATEGIES ===
from .search_strategies import (
    search_by_person,
    search_by_emotion,
    search_by_date,
    search_by_tags
)

__all__ = [
    # Constantes
    'DB_PATH', 'TEXTE_BASE_PATH',
    'POIDS_ROGET', 'POIDS_EMOTION', 'POIDS_TEMPOREL', 'POIDS_PERSONNES', 'POIDS_RESUME',
    'DEFAULT_TOP_K', 'MAX_TOKENS_CONTEXT',
    # DB
    '_get_connection', '_normalize_search',
    # Parsing
    '_parse_query', 'STOPWORDS',
    # Scoring
    '_score_candidates', '_proximite_tags', '_similarite_emotion',
    '_extract_weights', '_extract_filters', '_extract_strategy',
    # Core
    'run', '_search_metadata', '_load_texte_brut', '_format_context',
    # Stats
    'get_stats',
    # Search strategies
    'search_by_person', 'search_by_emotion', 'search_by_date', 'search_by_tags'
]