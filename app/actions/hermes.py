"""
hermes.py - Action de recherche sémantique dans les métadonnées
FAÇADE - Délègue tout à hermes_modules/

Recherche hybride avec pondération dynamique via QueryProfile

100% Python, 0% LLM, 100% déterministe.
Le QueryProfile est généré par Gemini Flash, Hermès l'applique sans le modifier.

Usage:
    from actions.hermes import run
    result = run({"query": "discussion sur les tags Roget", "top_k": 5})
    
    # Avec QueryProfile (recommandé)
    from utils.query_profiler import QueryProfiler
    profiler = QueryProfiler()
    profile = profiler.analyze("Qui travaillait sur MOSS?")
    result = run({"query": "Qui travaillait sur MOSS?", "profile": profile})
    
Via API:
    /go?action=hermes&query=tags+Roget&top_k=5
"""

from actions_config.common_header import *

# === IMPORTS DEPUIS HERMES_MODULES ===
from .hermes_modules import (
    # Fonction principale
    run,
    
    # Statistiques
    get_stats,
    
    # Recherches spécialisées
    search_by_person,
    search_by_emotion,
    search_by_date,
    search_by_tags,
    
    # Constantes (exposées pour rétrocompatibilité)
    DB_PATH,
    TEXTE_BASE_PATH,
    POIDS_ROGET,
    POIDS_EMOTION,
    POIDS_TEMPOREL,
    POIDS_PERSONNES,
    POIDS_RESUME
)


# === TEST ===
if __name__ == "__main__":
    print("=" * 60)
    print("HERMÈS - Test de l'action de recherche sémantique")
    print("=" * 60)
    
    # Test 0: Stats
    print("\n0. Statistiques de la base...")
    result = get_stats()
    if result["status"] == "success":
        print(f"   → Total segments: {result['stats']['total_segments']}")
        print(f"   → Période: {result['stats']['date_debut'][:10]} à {result['stats']['date_fin'][:10]}")
    else:
        print(f"   → Erreur: {result.get('error')}")
    
    # Test 1: Recherche simple (sans QueryProfile)
    print("\n1. Recherche 'tags Roget' (sans QueryProfile)...")
    result = run({"query": "discussion sur les tags Roget", "top_k": 3})
    print(f"   → Status: {result['status']}")
    print(f"   → Profile: {result.get('profile_used', {}).get('source', 'N/A')}")
    print(f"   → Résultats: {result['count']}")
    for seg in result.get("resultats", []):
        print(f"      [{seg['id']}] Score: {seg['score']:.3f} | {seg['resume_texte'][:50]}...")
    
    # Test 2: Recherche avec QueryProfile simulé
    print("\n2. Recherche 'Christian' (avec QueryProfile simulé)...")
    fake_profile = {
        "weights": {
            "tags_roget": 0.15,
            "emotion": 0.05,
            "timestamp": 0.20,
            "personnes": 0.50,
            "resume_texte": 0.10
        },
        "filters": {},
        "strategy": {"top_k": 3},
        "intent": "personne",
        "confidence": 0.90
    }
    result = run({"query": "conversations avec Christian", "profile": fake_profile})
    print(f"   → Status: {result['status']}")
    print(f"   → Profile: {result.get('profile_used', {}).get('source', 'N/A')}")
    print(f"   → Intent: {result.get('profile_used', {}).get('intent', 'N/A')}")
    print(f"   → Résultats: {result['count']}")
    if result.get("resultats"):
        seg = result["resultats"][0]
        print(f"   → Weights utilisés: {seg.get('scores_detail', {}).get('weights_used', {})}")
    
    # Test 3: Contexte formaté
    print("\n3. Contexte formaté pour l'Agent...")
    result = run({"query": "architecture MOSS", "top_k": 2})
    print(result.get("formatted_context", "")[:500])
    
    print("\n" + "=" * 60)
    print("✅ Tests terminés!")