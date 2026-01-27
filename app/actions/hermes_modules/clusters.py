"""
hermes_modules/clusters.py - Expansion de requêtes via Word2Vec
MOSS v0.10.4 - Session 70

Utilise un modèle Word2Vec pré-entraîné pour enrichir les requêtes
avec des termes sémantiquement similaires.

Exemple:
    Requête: "mémoire externe"
    Expansion: ["mémoire", "externe", "mémoire_persistante", "mémoire_délocalisée", 
                "stockage", "ssd", "mémoire_agnostique"]

Usage dans core.py:
    from .clusters import expand_query
    
    def run(params):
        query = params.get("query", "")
        expanded_terms = expand_query(query)  # ~10-50ms
        query_params = _parse_query(query, extra_terms=expanded_terms)
        ...
"""

import re
import unicodedata
import logging
from pathlib import Path
from typing import List, Set, Optional, Tuple

logger = logging.getLogger(__name__)

# === CONFIGURATION ===
MEMORY_DIR = Path.home() / "Dropbox" / "aiterego_memory"
MODEL_PATH = MEMORY_DIR / "models" / "clusters.model"

# Fallback si le modèle n'est pas dans models/
LEGACY_MODEL_PATH = MEMORY_DIR / "clusters_full.model"

# Paramètres d'expansion
DEFAULT_TOP_N = 5           # Nombre de termes similaires par mot
DEFAULT_MIN_SIMILARITY = 0.5  # Seuil de similarité minimum
MAX_EXPANSION_TERMS = 15    # Maximum de termes ajoutés au total

# Stopwords à ne pas expander
STOPWORDS = {
    'le', 'la', 'les', 'de', 'du', 'des', 'un', 'une', 'et', 'est', 'en',
    'que', 'qui', 'dans', 'pour', 'sur', 'avec', 'ce', 'se', 'ne', 'pas',
    'je', 'tu', 'il', 'nous', 'vous', 'on', 'tout', 'bien', 'très',
    'the', 'a', 'an', 'is', 'are', 'to', 'of', 'in', 'for', 'on', 'with'
}

# Cache du modèle (singleton)
_model = None
_model_loaded = False


def _normalize_text(text: str) -> str:
    """Normalise le texte (accents → ASCII)."""
    normalized = unicodedata.normalize('NFD', text)
    return normalized.encode('ascii', 'ignore').decode('utf-8').lower()


def _load_model():
    """Charge le modèle Word2Vec (lazy loading, singleton)."""
    global _model, _model_loaded
    
    if _model_loaded:
        return _model
    
    _model_loaded = True
    
    # Chercher le modèle
    model_path = None
    if MODEL_PATH.exists():
        model_path = MODEL_PATH
    elif LEGACY_MODEL_PATH.exists():
        model_path = LEGACY_MODEL_PATH
    
    if not model_path:
        logger.warning(f"⚠️ Modèle Word2Vec non trouvé: {MODEL_PATH}")
        return None
    
    try:
        from gensim.models import Word2Vec
        _model = Word2Vec.load(str(model_path))
        logger.info(f"✨ Word2Vec chargé: {len(_model.wv)} termes")
        return _model
    except ImportError:
        logger.warning("⚠️ gensim non installé - expansion désactivée")
        return None
    except Exception as e:
        logger.error(f"❌ Erreur chargement Word2Vec: {e}")
        return None


def get_similar_terms(
    term: str,
    top_n: int = DEFAULT_TOP_N,
    min_similarity: float = DEFAULT_MIN_SIMILARITY
) -> List[Tuple[str, float]]:
    """
    Retourne les termes similaires à un mot donné.
    
    Args:
        term: Le terme à rechercher
        top_n: Nombre maximum de résultats
        min_similarity: Score minimum (0-1)
    
    Returns:
        Liste de tuples (terme, score)
    """
    model = _load_model()
    if not model:
        return []
    
    # Normaliser le terme
    term_normalized = _normalize_text(term)
    
    # Essayer le terme original et normalisé
    for t in [term.lower(), term_normalized]:
        if t in model.wv:
            try:
                similaires = model.wv.most_similar(t, topn=top_n)
                # Filtrer par seuil de similarité
                return [(mot, score) for mot, score in similaires if score >= min_similarity]
            except Exception:
                pass
    
    return []


def expand_query(
    query: str,
    top_n: int = DEFAULT_TOP_N,
    min_similarity: float = DEFAULT_MIN_SIMILARITY,
    max_terms: int = MAX_EXPANSION_TERMS
) -> List[str]:
    """
    Expande une requête avec des termes sémantiquement similaires.
    
    Args:
        query: La requête originale
        top_n: Termes similaires par mot source
        min_similarity: Score minimum
        max_terms: Maximum de termes ajoutés
    
    Returns:
        Liste des termes d'expansion (sans les termes originaux)
    
    Exemple:
        >>> expand_query("mémoire externe")
        ['mémoire_persistante', 'stockage', 'ssd', 'mémoire_agnostique']
    """
    model = _load_model()
    if not model:
        return []
    
    # Tokeniser la requête
    words = re.findall(r'[a-zàâäéèêëïîôùûüÿœæç0-9]+', query.lower())
    
    # Filtrer les stopwords et mots trop courts
    query_terms = {w for w in words if w not in STOPWORDS and len(w) > 2}
    
    if not query_terms:
        return []
    
    # Collecter les expansions
    expansions: Set[str] = set()
    
    for term in query_terms:
        similaires = get_similar_terms(term, top_n=top_n, min_similarity=min_similarity)
        for mot, score in similaires:
            # Ne pas ajouter les termes déjà dans la requête
            mot_clean = mot.replace('_', ' ')  # "mémoire_externe" → "mémoire externe"
            if mot not in query_terms and mot_clean not in query.lower():
                expansions.add(mot)
    
    # Limiter le nombre total
    result = list(expansions)[:max_terms]
    
    if result:
        logger.debug(f"🔍 Expansion '{query}': +{len(result)} termes")
    
    return result


def expand_query_with_scores(
    query: str,
    top_n: int = DEFAULT_TOP_N,
    min_similarity: float = DEFAULT_MIN_SIMILARITY
) -> List[Tuple[str, float]]:
    """
    Comme expand_query mais retourne aussi les scores de similarité.
    Utile pour le debugging ou le scoring pondéré.
    """
    model = _load_model()
    if not model:
        return []
    
    words = re.findall(r'[a-zàâäéèêëïîôùûüÿœæç0-9]+', query.lower())
    query_terms = {w for w in words if w not in STOPWORDS and len(w) > 2}
    
    if not query_terms:
        return []
    
    expansions: dict = {}  # mot → meilleur score
    
    for term in query_terms:
        similaires = get_similar_terms(term, top_n=top_n, min_similarity=min_similarity)
        for mot, score in similaires:
            if mot not in query_terms:
                # Garder le meilleur score si le mot apparaît plusieurs fois
                if mot not in expansions or score > expansions[mot]:
                    expansions[mot] = score
    
    # Trier par score décroissant
    result = sorted(expansions.items(), key=lambda x: x[1], reverse=True)
    return result[:MAX_EXPANSION_TERMS]


def get_model_stats() -> dict:
    """Retourne des statistiques sur le modèle."""
    model = _load_model()
    if not model:
        return {"status": "not_loaded", "vocab_size": 0}
    
    return {
        "status": "loaded",
        "vocab_size": len(model.wv),
        "vector_size": model.wv.vector_size,
        "model_path": str(MODEL_PATH if MODEL_PATH.exists() else LEGACY_MODEL_PATH)
    }


# === TEST ===
if __name__ == "__main__":
    print("=" * 60)
    print("🧪 TEST EXPANSION WORD2VEC")
    print("=" * 60)
    
    # Stats
    stats = get_model_stats()
    print(f"\n📊 Modèle: {stats}")
    
    # Tests d'expansion
    requetes_test = [
        "mémoire externe",
        "Alex et Jérémie",
        "brevet MOSS",
        "Karen Barad posthumanisme",
        "architecture système",
        "scribe extraction"
    ]
    
    for query in requetes_test:
        expansions = expand_query(query)
        print(f"\n🔍 '{query}'")
        if expansions:
            print(f"   → +{len(expansions)}: {expansions[:8]}...")
        else:
            print(f"   → (aucune expansion)")
    
    # Test avec scores
    print(f"\n{'='*60}")
    print("📊 EXPANSION AVEC SCORES")
    print(f"{'='*60}")
    
    expansions_scores = expand_query_with_scores("mémoire externe")
    for mot, score in expansions_scores[:10]:
        print(f"   {score:.3f} - {mot}")
