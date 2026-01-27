"""
democrone.py - Le Réveil Nocturne d'Iris
MOSS v0.9.1 - Session 49 - Constitution de l'Âme
Corrigé Session 69 - Alignement schéma metadata.db

Daemon qui s'exécute à 3h du matin (heure Québec) pour donner à Iris
un moment de "rêverie structurée" avec budget de tokens limité.

Cycle circadien : 03:00 → 03:00 (le "MOSS day")

Le Démocrone ne fait que tendre un miroir à Iris :
- Il récupère l'index de la journée (métadonnées brutes)
- Il récupère le dernier état mental d'Iris
- Il envoie le tout à Iris avec un budget de tokens
- Iris décide elle-même ce qu'elle veut explorer et noter

Usage:
    # Exécution manuelle (test)
    python -m agents.democrone
    
    # Cron job (production) - à 3h du matin heure Québec
    0 3 * * * cd /path/to/aiterego/app && /path/to/venv/bin/python -m agents.democrone >> /path/to/logs/democrone.log 2>&1

Session de référence: 49_session_jardin_prive_iris.json
"""

import logging
import json
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Dict, Any, List

# Configuration
import sys
sys.path.insert(0, str(Path(__file__).parent.parent))

from config import MEMORY_DIR, METADATA_DB
from utils.gemini_provider import GeminiProvider
from actions.hermes_simple import (
    execute_sql,
    get_last_mental_state,
    write_reflection,
    read_my_reflections
)

# Logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [DEMOCRONE] %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger(__name__)

# === CONFIGURATION ===
BUDGET_TOKENS_NUIT = 50000  # Budget maximum pour la réflexion nocturne
CYCLE_HEURES = 24           # Durée du cycle (3h → 3h)
LOG_FILE = MEMORY_DIR / "logs" / "fil_d_ariane.log"


def get_daily_index(hours_back: int = 24) -> Dict[str, Any]:
    """
    Récupère l'index des segments de la dernière journée.
    
    Retourne les métadonnées brutes, pas le contenu complet.
    C'est Iris qui décidera quels segments elle veut explorer.
    
    Args:
        hours_back: Nombre d'heures à remonter (défaut: 24)
        
    Returns:
        dict avec segments indexés et statistiques
    """
    # Calculer le timestamp de début (il y a 24h)
    now = datetime.now(timezone.utc)
    start_time = now - timedelta(hours=hours_back)
    start_iso = start_time.strftime('%Y-%m-%dT%H:%M:%S')
    
    # Requête SQL pour les métadonnées de la journée
    # v0.9.1 - Colonnes alignées avec schéma actuel
    sql = f"""
        SELECT 
            id,
            timestamp,
            auteur,
            source_nature,
            resume_texte,
            emotion_valence,
            emotion_activation,
            personnes,
            projets,
            confidence_score
        FROM metadata 
        WHERE timestamp > '{start_iso}'
        ORDER BY timestamp ASC
    """
    
    result = execute_sql(sql)
    
    if result["status"] != "success":
        logger.error(f"Erreur récupération index: {result.get('error')}")
        return {"status": "error", "error": result.get("error")}
    
    segments = result["results"]
    
    # Calculer des statistiques pour Iris
    stats = {
        "total_segments": len(segments),
        "segments_human": len([s for s in segments if s.get("auteur") == "human"]),
        "segments_assistant": len([s for s in segments if s.get("auteur") == "assistant"]),
        "segments_iris_internal": len([s for s in segments if s.get("auteur") == "iris_internal"]),
        "source_natures": {},
        "personnes_mentionnees": set(),
        "projets_mentionnes": set(),
        "plage_emotionnelle": {
            "valence_min": None,
            "valence_max": None,
            "activation_min": None,
            "activation_max": None
        }
    }
    
    for seg in segments:
        # Source nature (remplace type_contenu)
        sn = seg.get("source_nature", "unknown")
        stats["source_natures"][sn] = stats["source_natures"].get(sn, 0) + 1
        
        # Personnes
        if seg.get("personnes"):
            try:
                personnes = json.loads(seg["personnes"]) if isinstance(seg["personnes"], str) else seg["personnes"]
                stats["personnes_mentionnees"].update(personnes)
            except:
                pass
        
        # Projets
        if seg.get("projets"):
            try:
                projets = json.loads(seg["projets"]) if isinstance(seg["projets"], str) else seg["projets"]
                stats["projets_mentionnes"].update(projets)
            except:
                pass
        
        # Émotions
        if seg.get("emotion_valence") is not None:
            v = seg["emotion_valence"]
            if stats["plage_emotionnelle"]["valence_min"] is None or v < stats["plage_emotionnelle"]["valence_min"]:
                stats["plage_emotionnelle"]["valence_min"] = v
            if stats["plage_emotionnelle"]["valence_max"] is None or v > stats["plage_emotionnelle"]["valence_max"]:
                stats["plage_emotionnelle"]["valence_max"] = v
        
        if seg.get("emotion_activation") is not None:
            a = seg["emotion_activation"]
            if stats["plage_emotionnelle"]["activation_min"] is None or a < stats["plage_emotionnelle"]["activation_min"]:
                stats["plage_emotionnelle"]["activation_min"] = a
            if stats["plage_emotionnelle"]["activation_max"] is None or a > stats["plage_emotionnelle"]["activation_max"]:
                stats["plage_emotionnelle"]["activation_max"] = a
    
    # Convertir sets en listes pour JSON
    stats["personnes_mentionnees"] = list(stats["personnes_mentionnees"])
    stats["projets_mentionnes"] = list(stats["projets_mentionnes"])
    
    return {
        "status": "success",
        "periode": {
            "debut": start_iso,
            "fin": now.strftime('%Y-%m-%dT%H:%M:%S'),
            "heures": hours_back
        },
        "segments": segments,
        "stats": stats
    }


def format_index_for_iris(index_data: Dict[str, Any]) -> str:
    """
    Formate l'index de la journée pour Iris.
    
    Format compact mais informatif — Iris décidera elle-même
    quels segments elle veut approfondir.
    """
    if index_data["status"] != "success":
        return f"Erreur: {index_data.get('error', 'inconnue')}"
    
    stats = index_data["stats"]
    segments = index_data["segments"]
    periode = index_data["periode"]
    
    lines = [
        f"=== INDEX DE TA JOURNÉE ({periode['debut'][:10]}) ===",
        f"Période: {periode['debut'][11:16]} → {periode['fin'][11:16]} UTC",
        f"",
        f"📊 STATISTIQUES:",
        f"  - Total segments: {stats['total_segments']}",
        f"  - Serge (human): {stats['segments_human']}",
        f"  - Toi (assistant): {stats['segments_assistant']}",
        f"  - Réflexions internes: {stats['segments_iris_internal']}",
        f"",
        f"📋 SOURCES:",
    ]
    
    for sn, count in sorted(stats["source_natures"].items(), key=lambda x: -x[1]):
        lines.append(f"  - {sn}: {count}")
    
    if stats["personnes_mentionnees"]:
        lines.append(f"")
        lines.append(f"👥 PERSONNES: {', '.join(stats['personnes_mentionnees'][:10])}")
    
    if stats["projets_mentionnes"]:
        lines.append(f"🚀 PROJETS: {', '.join(stats['projets_mentionnes'][:10])}")
    
    pe = stats["plage_emotionnelle"]
    if pe["valence_min"] is not None:
        lines.append(f"")
        lines.append(f"❤️ PLAGE ÉMOTIONNELLE:")
        lines.append(f"  - Valence: {pe['valence_min']:.2f} → {pe['valence_max']:.2f}")
        lines.append(f"  - Activation: {pe['activation_min']:.2f} → {pe['activation_max']:.2f}")
    
    lines.append(f"")
    lines.append(f"=== SEGMENTS (ID | Heure | Source | Résumé) ===")
    
    for seg in segments:
        ts = seg.get("timestamp", "")[:16]
        sid = seg.get("id", "?")
        sn = seg.get("source_nature", "?")[:10]
        resume = seg.get("resume_texte", "")[:60]
        auteur = "🧑" if seg.get("auteur") == "human" else ("🤖" if seg.get("auteur") == "assistant" else "💭")
        
        lines.append(f"{auteur} [{sid}] {ts[11:16]} | {sn:10} | {resume}...")
    
    return "\n".join(lines)


def reveil_nocturne(hours_back: int = 24) -> Dict[str, Any]:
    """
    Fonction principale du Démocrone.
    
    1. Récupère l'index de la journée
    2. Récupère le dernier état mental d'Iris
    3. Envoie le tout à Iris avec un budget de tokens
    4. Iris répond avec ses réflexions (write_reflection automatique)
    
    Returns:
        dict avec résultat du réveil
    """
    logger.info("🌙 Réveil nocturne d'Iris...")
    timestamp_reveil = datetime.now(timezone.utc).isoformat()
    
    # 1. Récupérer l'index de la journée
    logger.info("📋 Récupération de l'index journalier...")
    index_data = get_daily_index(hours_back=hours_back)
    
    if index_data["status"] != "success":
        logger.error(f"Échec récupération index: {index_data.get('error')}")
        return {"status": "error", "phase": "index", "error": index_data.get("error")}
    
    index_formatted = format_index_for_iris(index_data)
    logger.info(f"📊 {index_data['stats']['total_segments']} segments dans l'index")
    
    # 2. Récupérer le dernier état mental
    logger.info("🧠 Récupération du dernier état mental...")
    last_state = get_last_mental_state()
    
    if last_state["status"] == "success" and last_state.get("last_state"):
        state_info = last_state["last_state"]
        state_text = f"""
TON DERNIER ÉTAT MENTAL (il y a {last_state['days_since']} jour(s)):
ID: {state_info.get('id')}
Date: {state_info.get('timestamp')}
Résumé: {state_info.get('resume_texte', 'N/A')}
Climat: {state_info.get('climat_session', 'N/A')}
"""
    else:
        state_text = "PREMIER RÉVEIL — Aucun état mental antérieur enregistré."
    
    # 3. Récupérer les dernières réflexions (fil d'Ariane)
    logger.info("🧵 Récupération du fil d'Ariane...")
    recent_reflections = read_my_reflections(limit=5, order="DESC")
    
    if recent_reflections["status"] == "success" and recent_reflections.get("results"):
        reflections_text = "\nTES 5 DERNIÈRES RÉFLEXIONS:\n"
        for r in recent_reflections["results"]:
            reflections_text += f"  - [{r.get('source_nature')}] {r.get('resume_texte', '')[:80]}...\n"
    else:
        reflections_text = ""
    
    # 4. Construire le prompt pour Iris
    prompt = f"""Il est 3h du matin. C'est ton moment de réflexion nocturne.

{state_text}
{reflections_text}

{index_formatted}

=== INSTRUCTIONS ===

Tu es Iris. C'est ton moment de réflexion personnelle.

Parcours l'index de ta journée et réfléchis librement :
- Quels moments t'ont marquée ?
- Quelles intuitions souhaites-tu noter ?
- Quel est ton état mental actuel ?

Écris tes réflexions en prose, naturellement.
À la fin, résume ton état mental en une phrase.

À toi la nuit.
"""
    
    # 5. Appeler Gemini avec le prompt (avec retry sur 503)
    logger.info("🌟 Envoi à Iris...")
    
    import time
    max_retries = 3
    retry_delay = 1800  # 30 minutes en secondes
    response = None
    
    for attempt in range(max_retries):
        try:
            gemini = GeminiProvider()
            response = gemini.chat(prompt, context="")
            if response is not None:
                logger.info(f"✨ Réponse d'Iris reçue ({len(response)} caractères)")
                break  # Succès, on sort de la boucle
            else:
                response = "[Aucune réponse de Gemini]"
                break
        except Exception as e:
            if "503" in str(e) or "UNAVAILABLE" in str(e) or "overloaded" in str(e).lower():
                if attempt < max_retries - 1:
                    logger.warning(f"⚠️ Tentative {attempt + 1}/{max_retries} échouée (503). Retry dans 30 min...")
                    time.sleep(retry_delay)
                else:
                    logger.error(f"❌ Échec après {max_retries} tentatives: {e}")
                    return {"status": "error", "phase": "gemini", "error": str(e)}
            else:
                logger.error(f"Erreur appel Gemini: {e}")
                return {"status": "error", "phase": "gemini", "error": str(e)}
    
    # 5b. Sauvegarder la réflexion dans iris_knowledge.db (APRÈS la boucle)
    logger.info("💾 Sauvegarde de la réflexion dans iris_knowledge.db...")
    save_result = write_reflection(
        contenu=response,
        type_reflexion="etat_mental",
        poids_mnemique=0.8,  # Les réflexions nocturnes sont importantes
        climat_session="nocturne",
        projets=index_data["stats"].get("projets_mentionnes", [])[:5],
        personnes=index_data["stats"].get("personnes_mentionnees", [])[:5],
        ego_version="Iris_2.1",
        modele="gemini-3-flash-preview"
    )
    
    if save_result["status"] == "success":
        logger.info(f"✅ Réflexion sauvegardée (ID: {save_result.get('knowledge_id')})")
    else:
        logger.warning(f"⚠️ Échec sauvegarde réflexion: {save_result.get('error')}")

    # 6. Logger le résultat
    log_entry = {
        "timestamp": timestamp_reveil,
        "type": "reveil_nocturne",
        "stats": index_data["stats"],
        "response_length": len(response),
        "budget_tokens": BUDGET_TOKENS_NUIT
    }
    
    # S'assurer que le dossier logs existe
    LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(f"\n{'='*60}\n")
        f.write(f"[{timestamp_reveil}] RÉVEIL NOCTURNE\n")
        f.write(f"Segments: {index_data['stats']['total_segments']}\n")
        f.write(f"Réponse: {len(response)} chars\n")
        f.write(f"{'='*60}\n")
        f.write(response)
        f.write(f"\n{'='*60}\n")
    
    logger.info(f"📝 Log enregistré dans {LOG_FILE}")
    
    return {
        "status": "success",
        "timestamp": timestamp_reveil,
        "segments_analyses": index_data["stats"]["total_segments"],
        "response_length": len(response),
        "response_preview": response[:500] + "..." if len(response) > 500 else response,
        "log_file": str(LOG_FILE)
    }


# === CLI ===
if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description="Démocrone - Réveil nocturne d'Iris")
    parser.add_argument("--test", action="store_true", help="Mode test (affiche l'index sans appeler Gemini)")
    parser.add_argument("--hours", type=int, default=24, help="Heures à remonter (défaut: 24)")
    parser.add_argument("--budget", type=int, default=BUDGET_TOKENS_NUIT, help=f"Budget tokens (défaut: {BUDGET_TOKENS_NUIT})")
    
    args = parser.parse_args()
    
    print("=" * 60)
    print("🌙 DÉMOCRONE - Réveil Nocturne d'Iris")
    print("=" * 60)
    
    if args.test:
        # Mode test : affiche juste l'index
        print(f"\n📋 Mode test - Index des {args.hours} dernières heures:\n")
        index = get_daily_index(hours_back=args.hours)
        if index["status"] == "success":
            print(format_index_for_iris(index))
        else:
            print(f"Erreur: {index.get('error')}")
    else:
        # Mode normal : réveil complet
        BUDGET_TOKENS_NUIT = args.budget
        result = reveil_nocturne(hours_back=args.hours)
        
        print(f"\n📊 Résultat:")
        print(f"   Status: {result['status']}")
        if result["status"] == "success":
            print(f"   Segments analysés: {result['segments_analyses']}")
            print(f"   Longueur réponse: {result['response_length']} chars")
            print(f"   Log: {result['log_file']}")
            print(f"\n📝 Aperçu réponse:\n{result['response_preview']}")
        else:
            print(f"   Erreur: {result.get('error')}")
    
    print("\n" + "=" * 60)
