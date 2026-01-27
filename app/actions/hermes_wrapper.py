"""
hermes_wrapper.py - Le Bibliothécaire
MOSS v0.10.5 - Session 80 - Recherche textuelle unifiée + Recherche sémantique

OUTILS ACTIFS :
- search_files (recherche textuelle unifiée - scope ou dates)
- search_recent_files (alias → search_files avec scope approprié)
- search_memory (recherche sémantique SQL avec QueryProfiler + Hermès)
- read_knowledge (lire mémoire persistante)
- append_knowledge (ajouter à mémoire persistante)
- update_knowledge (modifier section mémoire persistante)

CASCADE DE RECHERCHE :
1. Fenêtre de contexte (déjà en mémoire Iris)
2. search_files / search_recent_files (scan textuel dans fichiers .txt)
3. search_memory (recherche sémantique SQL avec scoring pondéré)

CHANGELOG v0.10.5:
- Fusion search_files + search_recent_files en un seul module
- search_recent_files devient un alias avec scope="week"
- search_memory avec QueryProfiler + Hermès (recherche sémantique)
- lecture de documents externes et du code
"""

import logging
from pathlib import Path

# === IMPORTS ACTIFS ===
from actions.search_files import search_files
from library.knowledge import read_knowledge, append_knowledge, update_knowledge, create_knowledge, delete_knowledge, list_knowledge
from actions.inspect_memory import inspect_memory
from actions.consult_expert import consult_expert
from actions.search_documents import search_documents, get_document_stats

# === IMPORTS RECHERCHE SÉMANTIQUE ===
from utils.query_profiler import QueryProfiler
from actions.hermes import run as hermes_run
from library.emotions import get_emotional_resonance
from library.relations import get_relation_history
from library.chronologie import get_project_timeline
from library.piliers import get_piliers, add_pilier, update_pilier, delete_pilier
from library.web import search_web
from library.profile import read_profile
from actions.iris_knowledge import store_fact, query_facts, delete_fact, get_stats as knowledge_stats
from actions.hermes_simple import (
    delete_segment, 
    get_segments, 
    link_version,
    write_reflection,
    read_my_reflections,
    get_last_mental_state,
    explore_links
)

# Outils lecture de documents (Session 79)
from actions.read_document import list_documents, read_document, read_multiple_documents

logger = logging.getLogger(__name__)

# Instance unique du QueryProfiler (évite de le recréer à chaque appel)
_query_profiler = None

def _get_profiler():
    """Retourne l'instance unique du QueryProfiler (lazy init)."""
    global _query_profiler
    if _query_profiler is None:
        _query_profiler = QueryProfiler()
    return _query_profiler


# Aliases pour corriger les hallucinations d'outils (Session 52)
TOOL_ALIASES = {
    'search_segments': 'search_recent_files',
    'find_segments': 'search_recent_files',
    'find_in_files': 'search_files',
    'search_in_memory': 'search_memory',
    'search_hermes': 'search_memory',
    'search_semantic': 'search_memory',
    'search_db': 'search_memory',
}


def dispatch_tool(tool_name: str, arguments: dict):
    """
    Hermès v0.10.4 : Recherche textuelle + sémantique + Knowledge
    
    Outils actifs :
    - search_files : recherche textuelle (scope/days/dates)
    - search_recent_files : alias → search_files avec scope adapté
    - search_memory : recherche sémantique (QueryProfiler + Hermès + metadata.db)
    - read_knowledge, append_knowledge, update_knowledge : mémoire persistante
    """
    logger.info(f"📚 Hermès Dispatch: {tool_name} avec {arguments}")
    
    # Correction automatique des aliases (anti-hallucination)
    if tool_name in TOOL_ALIASES:
        original = tool_name
        tool_name = TOOL_ALIASES[tool_name]
        logger.warning(f"⚠️ Alias corrigé: {original} → {tool_name}")
    
    try:
        # === OUTIL RECHERCHE TEXTUELLE (unifié) ===
        if tool_name == "search_files":
            result = search_files(
                query=arguments.get("query"),
                scope=arguments.get("scope", "all"),
                days=arguments.get("days"),
                limit=arguments.get("limit", 20),
                date_start=arguments.get("date_start"),
                date_end=arguments.get("date_end"),
                context_chars=arguments.get("context_chars", 300)
            )
            if result.get("status") == "success":
                return result.get("summary", "Recherche terminée.")
            else:
                return f"Erreur: {result.get('error', 'Erreur inconnue')}"
        
        # === ALIAS RECHERCHE RÉCENTE ===
        elif tool_name == "search_recent_files":
            scope = arguments.get("scope", "week")
            days = arguments.get("days")
            
            result = search_files(
                query=arguments.get("query"),
                scope=scope,
                days=days,
                limit=arguments.get("limit", 20),
                context_chars=arguments.get("context_chars", 500)
            )
            if result.get("status") == "success":
                return result.get("summary", "Recherche terminée.")
            else:
                return f"Erreur: {result.get('error', 'Erreur inconnue')}"
        
        # === OUTIL RECHERCHE SÉMANTIQUE (QueryProfiler + Hermès) ===
        elif tool_name == "search_memory":
            query = arguments.get("query")
            if not query:
                return "Erreur: paramètre 'query' manquant pour search_memory"
            
            # 1. Analyser l'intention avec QueryProfiler
            profiler = _get_profiler()
            profile = profiler.analyze(query)
            
            logger.info(f"🎯 QueryProfile: intent={profile.intent}, confidence={profile.confidence}")
            logger.info(f"⚖️ Weights: {profile.weights}")
            
            # 2. Rechercher avec Hermès
            result = hermes_run({
                "query": query,
                "top_k": arguments.get("top_k", 5),
                "profile": profile,
                "format_context": True,
                "include_texte": arguments.get("include_texte", False)
            })
            
            if result.get("status") == "success":
                # Formater la réponse pour Iris
                return _format_memory_results(result, profile)
            else:
                return f"Erreur recherche mémoire: {result.get('error', 'Erreur inconnue')}"
        
        elif tool_name == "explore_links":
            segment_id = arguments.get("segment_id")
            if segment_id is None:
                return "Erreur: paramètre 'segment_id' manquant pour explore_links"
            
            result = explore_links(
                segment_id=int(segment_id),
                link_types=arguments.get("link_types"),
                depth=int(arguments.get("depth", 1)),
                max_results=int(arguments.get("max_results", 10))
            )
            
            if result.get("status") == "success":
                # Formatage simple
                links = result.get('results', [])
                output = f"🕸️ {result['links_found']} liens trouvés depuis segment {segment_id}\n"
                for link in links[:10]:
                    output += f"  [{link['link_type']}] ID:{link['linked_segment_id']} - {link.get('resume_texte', 'N/A')[:80]}\n"
                return output
            
            else:
                return f"Erreur explore_links: {result.get('error', 'Erreur inconnue')}"
            

        # === OUTIL AUDIT MÉMOIRE (v0.10.6) ===
        elif tool_name == "inspect_memory":
            result = inspect_memory(
                database=arguments.get("database", "episodic"),
                limit=arguments.get("limit", 50),
                offset=arguments.get("offset", 0),
                order=arguments.get("order", "recent"),
                filters=arguments.get("filters")
            )
            
            if result.get("status") == "success":
                output = f"🔍 AUDIT MÉMOIRE - {result['database']}\n"
                output += f"Total: {result.get('total_records', '?')} | Retournés: {result['returned']} | Offset: {result['offset']}\n"
                output += f"Ordre: {result.get('order', '?')}\n"
                
                # Métriques de qualité (si episodic)
                if result.get('quality_metrics'):
                    qm = result['quality_metrics']
                    output += f"\n📊 MÉTRIQUES QUALITÉ:\n"
                    output += f"  - Sans résumé: {qm.get('segments_sans_resume', '?')}\n"
                    output += f"  - Sans tags Roget: {qm.get('segments_sans_tags', '?')}\n"
                    output += f"  - Sans personnes: {qm.get('segments_sans_personnes', '?')}\n"
                    output += f"  - Doublons potentiels: {qm.get('doublons_potentiels', '?')}\n"
                    if qm.get('score_emotionnel_moyen'):
                        output += f"  - Score émotionnel moyen: {qm['score_emotionnel_moyen']}\n"
                    if qm.get('distribution_types'):
                        output += f"  - Types: {qm['distribution_types']}\n"
                
                # Données brutes (limiter à 20 pour la lisibilité)
                output += f"\n📋 DONNÉES BRUTES ({result['returned']} lignes):\n"
                for i, row in enumerate(result.get('results', [])[:20], 1):
                    output += f"\n--- [{i}] ID: {row.get('id', '?')} ---\n"
                    output += f"  Timestamp: {row.get('timestamp', '?')}\n"
                    output += f"  Source: {row.get('source_file', '?')}\n"
                    resume = row.get('resume_texte', '')
                    if resume:
                        output += f"  Résumé: {resume[:200]}{'...' if len(resume) > 200 else ''}\n"
                    output += f"  Type: {row.get('type_contenu', '?')}\n"
                    output += f"  Auteur: {row.get('auteur', '?')}\n"
                    tags = row.get('tags_roget', '')
                    if tags:
                        output += f"  Tags Roget: {tags[:100]}{'...' if len(tags) > 100 else ''}\n"
                    if row.get('personnes'):
                        output += f"  Personnes: {row['personnes']}\n"
                    if row.get('score_emotionnel'):
                        output += f"  Score émotionnel: {row['score_emotionnel']}\n"
                
                if result['returned'] > 20:
                    output += f"\n[... {result['returned'] - 20} lignes supplémentaires non affichées ...]\n"
                
                return output
            else:
                return f"Erreur inspect_memory: {result.get('error')}"
        
        # === OUTILS KNOWLEDGE (Mémoire persistante Iris) ===
        elif tool_name == "read_knowledge":
            result = read_knowledge(
                fichier=arguments.get("fichier")
            )
            if result.get("status") == "success":
                return result.get("contenu")
            else:
                return f"Erreur: {result.get('error')} | Fichiers disponibles: {result.get('fichiers_disponibles', [])}"
        
        elif tool_name == "append_knowledge":
            result = append_knowledge(
                fichier=arguments.get("fichier"),
                contenu=arguments.get("contenu")
            )
            if result.get("status") == "success":
                return result.get("message")
            else:
                return f"Erreur: {result.get('error')}"
        
        elif tool_name == "update_knowledge":
            result = update_knowledge(
                fichier=arguments.get("fichier"),
                section=arguments.get("section"),
                contenu=arguments.get("contenu")
            )
            if result.get("status") == "success":
                return result.get("message")
            else:
                error_msg = f"Erreur: {result.get('error')}"
                if result.get("sections_disponibles"):
                    error_msg += f" | Sections: {result.get('sections_disponibles')}"
                return error_msg

        elif tool_name == "create_knowledge":
            result = create_knowledge(
                fichier=arguments.get("fichier"),
                contenu=arguments.get("contenu", "")
            )
            if result.get("status") == "success":
                return result.get("message")
            else:
                return f"Erreur: {result.get('error')}"
        
        elif tool_name == "delete_knowledge":
            result = delete_knowledge(
                fichier=arguments.get("fichier")
            )
            if result.get("status") == "success":
                return result.get("message")
            else:
                return f"Erreur: {result.get('error')} | Fichiers disponibles: {result.get('fichiers_disponibles', [])}"
        
        elif tool_name == "list_knowledge":
            result = list_knowledge()
            if result.get("status") == "success":
                fichiers = result.get("fichiers", [])
                if not fichiers:
                    return "Aucun fichier dans ta mémoire persistante."
                output = f"📁 {result['count']} fichiers dans {result['chemin']}:\n"
                for f in fichiers:
                    output += f"  - {f['nom']}.md ({f['taille']} octets, modifié {f['modifie']})\n"
                return output
            else:
                return f"Erreur: {result.get('error')}"

        # === OUTILS IRIS_KNOWLEDGE (Mémoire sémantique SQL) ===
        elif tool_name == "store_fact":
            result = store_fact(
                domaine=arguments.get("domaine"),
                sujet=arguments.get("sujet"),
                information=arguments.get("information"),
                importance=arguments.get("importance", 3),
                metadata=arguments.get("metadata"),
                source_id=arguments.get("source_id")
            )
            if result.get("status") == "success":
                action = "Mis à jour" if result.get("action") == "updated" else "Créé"
                return f"{action}: {result['domaine']}/{result['sujet']} (id={result['id']})"
            else:
                return f"Erreur: {result.get('error')}"
        
        elif tool_name == "query_facts":
            result = query_facts(
                domaine=arguments.get("domaine"),
                sujet=arguments.get("sujet"),
                search=arguments.get("search"),
                min_importance=arguments.get("min_importance", 1),
                limit=arguments.get("limit", 10)
            )
            if result.get("status") == "success":
                facts = result.get("facts", [])
                if not facts:
                    return "Aucun fait trouvé."
                output = f"📚 {result['count']} fait(s) trouvé(s):\n"
                for f in facts:
                    output += f"  [{f['domaine']}/{f['sujet']}] (importance={f['importance']}) {f['information'][:100]}...\n" if len(f['information']) > 100 else f"  [{f['domaine']}/{f['sujet']}] (importance={f['importance']}) {f['information']}\n"
                return output
            else:
                return f"Erreur: {result.get('error')}"
        
        elif tool_name == "delete_fact":
            result = delete_fact(
                id=arguments.get("id"),
                domaine=arguments.get("domaine"),
                sujet=arguments.get("sujet")
            )
            if result.get("status") == "success":
                return f"Supprimé: {result['deleted']}"
            else:
                return f"Erreur: {result.get('error')}"
        
        # === OUTIL NULL (conversation simple) ===
        elif tool_name is None or tool_name == "null":
            return None
        
        # === OUTILS LECTURE DOCUMENTS (fenêtre 1M tokens dédiée) ===
        elif tool_name == "list_documents":
            source = arguments.get("source", "documents")
            result = list_documents(source=source)
            
            if result.get("status") == "success":
                fichiers = result.get("fichiers", [])
                if not fichiers:
                    return f"📁 Aucun fichier dans {source}. Chemin: {result.get('chemin')}"
                
                output = f"📁 {result['total']} fichiers dans {source} ({result.get('description')}):\n"
                for f in fichiers[:20]:  # Limiter à 20 pour la lisibilité
                    output += f"  - {f['chemin_relatif']} ({f['taille_lisible']})\n"
                
                if result['total'] > 20:
                    output += f"  ... et {result['total'] - 20} autres fichiers\n"
                
                return output
            else:
                return f"Erreur: {result.get('error')}"
        
        elif tool_name == "read_document":
            fichier = arguments.get("fichier")
            if not fichier:
                return "Erreur: paramètre 'fichier' manquant"
            
            result = read_document(
                fichier=fichier,
                source=arguments.get("source", "documents"),
                question=arguments.get("question")
            )
            
            if result.get("status") == "success":
                # Retourner la synthèse de Gemini + trace légère
                trace = result.get("trace", {})
                output = f"📖 Lecture de {fichier} ({trace.get('taille_lisible', '?')}, ~{trace.get('taille_tokens', 0)} tokens)\n"
                output += f"Checksum: {trace.get('checksum', '?')}\n\n"
                output += result.get("synthese", "")
                return output
            else:
                return f"Erreur: {result.get('error')}"
        
        elif tool_name == "read_multiple_documents":
            fichiers = arguments.get("fichiers")
            if not fichiers:
                return "Erreur: paramètre 'fichiers' manquant (liste de noms)"
            
            result = read_multiple_documents(
                fichiers=fichiers,
                source=arguments.get("source", "code"),
                question=arguments.get("question")
            )
            
            if result.get("status") == "success":
                output = f"📚 {result['fichiers_lus']} fichiers lus (~{result['tokens_total']} tokens total)\n\n"
                output += result.get("synthese", "")
                
                if result.get("erreurs"):
                    output += f"\n\n⚠️ Erreurs: {', '.join(result['erreurs'])}"
                
                return output
            else:
                return f"Erreur: {result.get('error')}"
            
        # === OUTIL CONSULTATION EXPERT (MoA - Mixture of Agents) ===
        elif tool_name == "consult_expert":
            query = arguments.get("query")
            if not query:
                return "Erreur: paramètre 'query' manquant pour consult_expert"
            
            result = consult_expert(
                query=query,
                expertise=arguments.get("expertise", "reasoning"),
                context=arguments.get("context")
            )
            
            if result.get("status") == "success":
                expertise = result.get("expertise", "unknown")
                model = result.get("model_used", "unknown")
                response = result.get("response", "")
                
                return f"🎓 Analyse expert ({expertise}, modèle: {model}):\n\n{response}"
            else:
                return f"Erreur consultation expert: {result.get('error', 'Erreur inconnue')}"
            
        # === OUTIL RECHERCHE DOCUMENTS (INDEX Dropbox) ===
        elif tool_name == "search_documents":
            query = arguments.get("query")
            if not query:
                return "Erreur: paramètre 'query' manquant pour search_documents"
            
            result = search_documents(
                query=query,
                domain=arguments.get("domain"),
                extension=arguments.get("extension"),
                limit=arguments.get("limit", 10),
                min_importance=arguments.get("min_importance", 1)
            )
            
            if result.get("status") == "success":
                return result.get("summary", f"{result['count']} documents trouvés.")
            else:
                return f"Erreur: {result.get('error', 'Erreur inconnue')}"
        
        # === TOUS LES AUTRES : DÉSACTIVÉS ===
        else:
            logger.warning(f"⚠️ Outil '{tool_name}' non disponible en mode stabilisation")
            return f"Mode stabilisation : outils actifs = search_files, search_recent_files, search_memory, read_knowledge, append_knowledge, update_knowledge. Tu as demandé '{tool_name}'."
            
    except Exception as e:
        logger.error(f"Erreur Hermès Dispatch: {e}")
        import traceback
        traceback.print_exc()
        return f"Erreur technique: {str(e)}"


def _format_memory_results(result: dict, profile) -> str:
    """
    Formate les résultats de search_memory pour Iris.
    Inclut les informations sur le profil utilisé et les blocs thématiques.
    v0.10.5 - Ajout des IDs pour permettre explore_links
    """
    segments = result.get("resultats", [])
    count = result.get("count", 0)
    
    if count == 0:
        return f"Aucun segment trouvé dans la mémoire sémantique. Intent détecté: {profile.intent} (confiance: {profile.confidence:.0%})"
    
    # Header avec contexte
    output = [f"=== RECHERCHE MÉMOIRE SÉMANTIQUE ==="]
    output.append(f"Intent: {profile.intent} | Confiance: {profile.confidence:.0%}")
    output.append(f"Segments trouvés: {count}")
    output.append("")
    
    # Grouper par gr_id si disponible
    gr_ids = {}
    for seg in segments:
        gr_id = seg.get("gr_id") or "sans_bloc"
        if gr_id not in gr_ids:
            gr_ids[gr_id] = []
        gr_ids[gr_id].append(seg)
    
    # Afficher les résultats
    for gr_id, segs in gr_ids.items():
        if gr_id != "sans_bloc" and len(segs) > 1:
            output.append(f"--- BLOC THÉMATIQUE (gr_id: {gr_id}) - {len(segs)} segments ---")
        
        for seg in segs:
            seg_id = seg.get("id", "?")  # <-- NOUVEAU
            date = seg.get("timestamp", "?")[:10]
            score = seg.get("score", 0)
            resume = seg.get("resume_texte", "")[:200]
            personnes = seg.get("personnes", "")
            
            output.append(f"[ID: {seg_id}] [{date}] Score: {score:.2f}")  # <-- MODIFIÉ
            if personnes:
                output.append(f"  Personnes: {personnes}")
            output.append(f"  {resume}...")
            output.append("")
    
    # Poids utilisés (pour debug/transparence)
    weights = profile.weights
    top_weights = sorted(weights.items(), key=lambda x: x[1], reverse=True)[:3]
    weights_str = ", ".join([f"{k}={v:.0%}" for k, v in top_weights])
    output.append(f"[Poids dominants: {weights_str}]")
    
    return "\n".join(output)
