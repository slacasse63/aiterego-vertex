"""
hermes_modules/core.py - Cœur d'Hermès
MOSS v0.10.4 - Session 62 - Fix schéma v2.1

Contient la fonction principale run() et les fonctions d'orchestration.
"""

import json
import logging
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Any

from actions_config.common_header import get_timestamp
from .config import (
    DB_PATH, TEXTE_BASE_PATH, DEFAULT_TOP_K, MAX_TOKENS_CONTEXT,
    POIDS_ROGET, POIDS_EMOTION, POIDS_TEMPOREL, POIDS_PERSONNES, POIDS_RESUME
)
from .db import _get_connection, _normalize_search
from .parsing import _parse_query
from .scoring import (
    _score_candidates, _extract_weights, _extract_filters, _extract_strategy
)

# Expansion Word2Vec (optionnel - échoue silencieusement si modèle absent)
try:
    from .clusters import expand_query
    WORD2VEC_AVAILABLE = True
except ImportError:
    WORD2VEC_AVAILABLE = False
    expand_query = lambda q: []

logger = logging.getLogger(__name__)


def run(params: dict) -> dict:
    """
    Recherche sémantique dans les métadonnées.
    
    Params:
        query (str): Requête en langage naturel
        top_k (int, optional): Nombre de résultats (défaut: 5)
        include_texte (bool, optional): Charger le texte brut (défaut: False)
        format_context (bool, optional): Retourner le contexte formaté pour l'Agent (défaut: True)
        profile (QueryProfile, optional): Profil de pondération dynamique
        
    Returns:
        dict avec:
            - status: "success" ou "error"
            - query: requête originale
            - resultats: liste de segments trouvés
            - formatted_context: contexte prêt pour l'Agent (si format_context=True)
            - count: nombre de résultats
            - timestamp: horodatage UTC
            - profile_used: informations sur le profil utilisé
    """
    query = params.get("query")
    top_k = params.get("top_k", DEFAULT_TOP_K)
    include_texte = params.get("include_texte", False)
    format_context = params.get("format_context", True)
    profile = params.get("profile", None)

    logger.info(f"🔍 HERMÈS reçu - query: {query}, profile: {profile is not None}")
    
    if not query:
        return {
            "status": "error",
            "error": "Paramètre 'query' manquant",
            "timestamp": get_timestamp()
        }
    
    # Extraire les poids du profile ou utiliser les défauts
    if profile is not None:
        weights = _extract_weights(profile)
        filters = _extract_filters(profile)
        strategy = _extract_strategy(profile)
        profile_info = {
            "source": "QueryProfile",
            "intent": getattr(profile, 'intent', 'unknown'),
            "confidence": getattr(profile, 'confidence', 0.0),
            "weights": weights
        }
        # Utiliser top_k du profile si non spécifié explicitement
        if "top_k" not in params and strategy.get("top_k"):
            top_k = strategy["top_k"]
    else:
        weights = {
            "tags_roget": POIDS_ROGET,
            "emotion": POIDS_EMOTION,
            "timestamp": POIDS_TEMPOREL,
            "personnes": POIDS_PERSONNES,
            "resume_texte": POIDS_RESUME
        }
        filters = {}
        strategy = {"include_text_fallback": True}
        profile_info = {
            "source": "default",
            "weights": weights
        }
    
    try:
        # 1. Parser la requête
        query_params = _parse_query(query)
        
        # 1b. Expansion Word2Vec
        if WORD2VEC_AVAILABLE:
            expanded_terms = expand_query(query)
            if expanded_terms:
                query_params['mots_cles'].extend(expanded_terms)
                logger.info(f"🧠 Expansion: +{len(expanded_terms)} termes")
        
        logger.info(f"🔍 HERMÈS parsed - mots_cles: {query_params['mots_cles']}, personnes: {query_params.get('personnes', [])}")
        
        # 2. Appliquer les filtres du profile
        if filters.get("date_range_days"):
            now = datetime.now(timezone.utc)
            query_params["date_debut"] = now - timedelta(days=filters["date_range_days"])
            query_params["date_fin"] = now
        # NOTE: type_contenu et domaine supprimés du schéma v2.1
        
        # 3. Rechercher dans les métadonnées
        candidats = _search_metadata(query_params)
        
        if not candidats:
            # FALLBACK: recherche dans le texte brut
            if strategy.get("include_text_fallback", True):
                try:
                    from actions.search import search_in_directory
                    fallback_result = search_in_directory("echanges", query)
                    
                    if fallback_result["status"] == "success" and fallback_result["total_occurrences"] > 0:
                        # Convertir les résultats fallback en format Hermès
                        resultats = []
                        for fichier_result in fallback_result["resultats"][:top_k]:
                            resultats.append({
                                "id": None,
                                "timestamp": "",
                                "source_file": fichier_result["fichier"],
                                "token_start": 0,
                                "tags_roget": [],
                                "emotion_valence": 0.0,
                                "emotion_activation": 0.0,
                                "gr_id": None,
                                "resume_texte": fichier_result["resultats"][0]["contenu"][:200] if fichier_result["resultats"] else "",
                                "score": 0.1,
                                "scores_detail": {"roget": 0, "emotion": 0, "temporel": 0, "personnes": 0, "resume": 0, "fallback": True},
                                "texte_brut": None
                            })
                        
                        return {
                            "status": "success",
                            "query": query,
                            "resultats": resultats,
                            "formatted_context": _format_context(resultats),
                            "count": len(resultats),
                            "fallback": True,
                            "profile_used": profile_info,
                            "timestamp": get_timestamp()
                        }
                except ImportError:
                    pass  # Module search non disponible
            
            # Vraiment rien trouvé
            return {
                "status": "success",
                "query": query,
                "resultats": [],
                "formatted_context": "",
                "count": 0,
                "profile_used": profile_info,
                "timestamp": get_timestamp()
            }
        
        # 4. Scorer les candidats avec les poids dynamiques
        scored = _score_candidates(candidats, query_params, weights)
        
        # 5. Trier et limiter
        scored.sort(key=lambda x: x["score"], reverse=True)
        resultats = scored[:top_k]
        
        # 6. Charger le texte brut si demandé
        if include_texte:
            _load_texte_brut(resultats)
        
        # 7. Formater le contexte pour l'Agent
        formatted = _format_context(resultats) if format_context else ""
        
        return {
            "status": "success",
            "query": query,
            "parsed_params": {
                "mots_cles": query_params["mots_cles"],
                "tags_explicites": query_params["tags_explicites"],
                "personnes": query_params.get("personnes", [])
            },
            "resultats": resultats,
            "formatted_context": formatted,
            "count": len(resultats),
            "profile_used": profile_info,
            "timestamp": get_timestamp()
        }
        
    except Exception as e:
        import traceback
        traceback.print_exc()
        return {
            "status": "error",
            "error": f"Erreur lors de la recherche: {str(e)}",
            "query": query,
            "timestamp": get_timestamp()
        }


def _search_metadata(params: dict, limit: int = 100) -> List[dict]:
    """
    Requête SQLite pour trouver les candidats.
    Utilise OR entre les mots-clés/tags/personnes pour plus de flexibilité.
    
    Schéma v2.1 - Colonnes disponibles:
    - id, timestamp, timestamp_epoch, token_start, token_end
    - source_file, source_nature, source_format, source_origine
    - auteur, emotion_valence, emotion_activation, tags_roget
    - personnes, projets, sujets, lieux, resume_texte, gr_id
    - pilier, vecteur_trildasa, poids_mnemique, ego_version
    - modele, date_creation, confidence_score
    """
    conn = _get_connection()
    
    # Construire la requête dynamiquement
    conditions = []
    values = []
    
    # Filtre par date (AND - c'est une plage)
    if params.get("date_debut"):
        conditions.append("timestamp >= ?")
        date_debut = params["date_debut"]
        if hasattr(date_debut, 'isoformat'):
            values.append(date_debut.isoformat())
        else:
            values.append(str(date_debut))
    if params.get("date_fin"):
        conditions.append("timestamp <= ?")
        date_fin = params["date_fin"]
        if hasattr(date_fin, 'isoformat'):
            values.append(date_fin.isoformat())
        else:
            values.append(str(date_fin))
    
    # Filtre par mots-clés dans le résumé (OR entre les mots)
    # SKIP si on cherche par personnes
    mots_cles = params.get("mots_cles", [])[:5]
    if not params.get("personnes") and mots_cles:
        mot_conditions = []
        for mot in mots_cles:
            # Schéma v2.1: resume_texte, sujets, projets, lieux (pas resume_mots_cles, pas organisations)
            mot_conditions.append("(resume_texte LIKE ? OR sujets LIKE ? OR projets LIKE ? OR lieux LIKE ?)")
            values.extend([f"%{mot}%", f"%{mot}%", f"%{mot}%", f"%{mot}%"])
        # Joindre avec OR au lieu de AND
        conditions.append("(" + " OR ".join(mot_conditions) + ")")
    
    # Filtre par tags Roget (OR entre les tags)
    tags = params.get("tags_explicites", [])
    if tags:
        tag_conditions = []
        for tag in tags:
            tag_conditions.append("tags_roget LIKE ?")
            values.append(f"%{tag}%")
        conditions.append("(" + " OR ".join(tag_conditions) + ")")
    
    # Filtre par personnes (OR entre les personnes)
    personnes = params.get("personnes", [])[:3]
    if personnes:
        personne_conditions = []
        for personne in personnes:
            personne_norm = _normalize_search(personne)
            personne_conditions.append("normalize_search(personnes) LIKE ?")
            values.append(f"%{personne_norm}%")
        conditions.append("(" + " OR ".join(personne_conditions) + ")")
    
    # Construire le WHERE
    where_clause = " AND ".join(conditions) if conditions else "1=1"
    
    # Schéma v2.1: colonnes disponibles (sans type_contenu, domaine, resume_mots_cles, organisations)
    query = f"""
        SELECT id, timestamp, source_file, token_start, tags_roget,
               emotion_valence, emotion_activation, gr_id, confidence_score,
               resume_texte, personnes, vecteur_trildasa, projets, sujets
        FROM metadata
        WHERE {where_clause}
        ORDER BY timestamp DESC
        LIMIT ?
    """
    values.append(limit)
    
    cursor = conn.execute(query, values)
    
    segments = []
    for row in cursor:
        # Parser tags_roget JSON
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
            "gr_id": row['gr_id'] if 'gr_id' in row.keys() else None,
            "confidence_score": row['confidence_score'] if 'confidence_score' in row.keys() else None,
            "resume_texte": row['resume_texte'] or '',
            "personnes": row['personnes'] if 'personnes' in row.keys() else '',
            "projets": row['projets'] if 'projets' in row.keys() else '',
            "sujets": row['sujets'] if 'sujets' in row.keys() else '',
            "vecteur_trildasa": row["vecteur_trildasa"] if "vecteur_trildasa" in row.keys() else None,
            "score": 0.0,
            "texte_brut": None
        })
    
    conn.close()
    return segments


def _load_texte_brut(segments: List[dict]) -> None:
    """
    Charge le texte brut depuis les fichiers source.
    Modifie les segments in-place.
    """
    for segment in segments:
        try:
            fichier_path = TEXTE_BASE_PATH / segment["source_file"]
            if fichier_path.exists():
                with open(fichier_path, 'r', encoding='utf-8') as f:
                    contenu = f.read()
                    # TODO: Extraire le segment exact basé sur token_start
                    segment["texte_brut"] = contenu[:2000]
            else:
                segment["texte_brut"] = f"[Fichier non trouvé: {segment['source_file']}]"
        except Exception as e:
            segment["texte_brut"] = f"[Erreur lecture: {e}]"


def _format_context(segments: List[dict], max_tokens: int = MAX_TOKENS_CONTEXT) -> str:
    """
    Formate les segments pour injection dans le prompt de l'Agent.
    Schéma v2.1: utilise gr_id au lieu de type_contenu/domaine
    """
    if not segments:
        return ""
    
    max_chars = max_tokens * 4
    
    lines = ["--- CONTEXTE MÉMOIRE ---\n"]
    current_chars = len(lines[0])
    
    for i, seg in enumerate(segments, 1):
        # Schéma v2.1: gr_id remplace type_contenu/domaine
        gr_info = f"bloc:{seg.get('gr_id', '?')}" if seg.get('gr_id') else ""
        conf_info = f"conf:{seg.get('confidence_score', 0):.2f}" if seg.get('confidence_score') else ""
        
        header = f"\n[Mémoire {i}] {seg['timestamp'][:10] if seg['timestamp'] else 'N/A'} | {gr_info} {conf_info} | Score: {seg['score']:.2f}\n"
        resume = f"Résumé: {seg['resume_texte']}\n" if seg['resume_texte'] else ""
        
        # Ajouter personnes si disponibles
        personnes_info = ""
        if seg.get('personnes') and seg['personnes'] != '[]':
            personnes_info = f"Personnes: {seg['personnes']}\n"
        
        texte = ""
        if seg.get("texte_brut") and not seg["texte_brut"].startswith("["):
            texte = f"Extrait: {seg['texte_brut'][:500]}...\n" if len(seg['texte_brut']) > 500 else f"Texte: {seg['texte_brut']}\n"
        
        bloc = header + personnes_info + resume + texte
        
        if current_chars + len(bloc) > max_chars:
            lines.append("\n[... contexte tronqué ...]\n")
            break
        
        lines.append(bloc)
        current_chars += len(bloc)
    
    lines.append("\n--- FIN CONTEXTE ---\n")
    
    return "".join(lines)
