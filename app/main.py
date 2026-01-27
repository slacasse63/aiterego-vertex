"""
main.py - AIter Ego / MOSS v0.10.2
Architecture simplifiée : Iris avec outil search_files
Session 55 - Ajout chaînage d'outils (max 3 appels consécutifs)
Session 61 - Intégration Scribe v4.1 (gr_id + confidence_score)

CHANGELOG v0.10.2:
- Correction signature _insert_metadata (ajout token_end)
- Déclenchement Scribe batch après rotate_window()
- Scribe temps réel utilise get_insert_fn() pour cohérence
"""

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from datetime import datetime, timezone
from pathlib import Path
import logging
from logging.handlers import RotatingFileHandler
import asyncio
import re
import json
import threading

# Configuration
from config import HOST, PORT, DATA_DIR, BUFFER_DIR, ECHANGES_DIR
from utils.context_window import (
    count_tokens, should_rotate, rotate_window, 
    get_window_status, validate_input_size, 
    process_large_input, initialize_window, THRESHOLD, MAX_INPUT
)

# Providers et Agents
from utils.gemini_provider import GeminiProvider
from agents.scribe import Scribe
from agents import arachne

# Le Bibliothécaire
from actions.hermes_wrapper import dispatch_tool

# === CONFIGURATION ===
MAX_TOOL_CHAIN = 5  # Nombre max d'appels d'outils consécutifs

# === CONFIGURATION LOGS ===

# Dossier des logs
LOGS_DIR = Path.home() / "Dropbox" / "aiterego_memory" / "logs"
LOGS_DIR.mkdir(parents=True, exist_ok=True)

# Filtre pour masquer les /health dans la console
class HealthCheckFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        return "/health" not in record.getMessage()

# Format des logs
log_format = "%(asctime)s [%(name)s] %(levelname)s: %(message)s"
date_format = "%Y-%m-%d %H:%M:%S"

# Logger racine
root_logger = logging.getLogger()
root_logger.setLevel(logging.INFO)

# Nettoyer les handlers existants (évite les doublons)
root_logger.handlers.clear()

# Handler CONSOLE (sans les /health)
console_handler = logging.StreamHandler()
console_handler.setFormatter(logging.Formatter(log_format, date_format))
console_handler.addFilter(HealthCheckFilter())
root_logger.addHandler(console_handler)

# Handler FICHIER (avec tout, y compris /health pour audit)
log_file = LOGS_DIR / f"moss_{datetime.now().strftime('%Y-%m-%d')}.log"
file_handler = RotatingFileHandler(log_file, maxBytes=5*1024*1024, backupCount=10)
file_handler.setFormatter(logging.Formatter(log_format, date_format))
root_logger.addHandler(file_handler)

# Forcer tous les loggers à utiliser notre handler fichier
for logger_name in ['uvicorn', 'uvicorn.access', 'uvicorn.error', 'httpx', 'google_genai', 'google_genai.models', 'google_genai.types', '__main__', 'utils.trildasa_engine']:
    logging.getLogger(logger_name).addHandler(file_handler)

# Appliquer le filtre au logger Uvicorn aussi
logging.getLogger("uvicorn.access").addFilter(HealthCheckFilter())

# Logger pour ce module
logger = logging.getLogger(__name__)

# Fichiers
FENETRE_ACTIVE = DATA_DIR / "fenetre_active.txt"

# Instances Globales
gemini = GeminiProvider()
_scribe_instance = None
_scribe_insert_fn = None  # Fonction d'insertion pour temps réel
_token_counter = 0  # Compteur de tokens pour temps réel


def get_scribe() -> Scribe:
    global _scribe_instance, _scribe_insert_fn
    if _scribe_instance is None:
        _scribe_instance = Scribe(mode="gemini", parallel_batches=0, batch_size=2)
        _scribe_insert_fn = _scribe_instance.get_insert_fn(
            source_file="realtime",
            source_origine="iris_realtime"
        )
        logger.info("✨ Scribe v4.1 initialisé (gr_id + confidence_score)")
    return _scribe_instance


def get_timestamp_zulu() -> str:
    return datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%S.%f')[:-3] + 'Z'


# === DÉTECTION D'OUTILS (JSON) ===

def extract_tool_call(response: str):
    """
    Détecte un appel d'outil (JSON) de manière robuste, avec ou sans balises Markdown.
    v0.10.5 - Corrige le bug où JSON mélangé à du texte était ignoré.
    Retourne None si la réponse est du texte normal (pas un appel d'outil).
    """
    if not response:
        return None
        
    clean_response = response.strip()
    
    # Stratégie A : Balises Markdown explicites (prioritaire)
    pattern_strict = r'```json\s*({.*?})\s*```'
    match = re.search(pattern_strict, clean_response, re.DOTALL | re.IGNORECASE)
    if match:
        try:
            data = json.loads(match.group(1))
            if "tool" in data:
                return data
        except json.JSONDecodeError:
            pass
    
    # Stratégie B : JSON {"tool": ...} n'importe où dans la réponse
    # Cherche spécifiquement un objet avec "tool" comme clé
    # Gère les args imbriqués avec une approche plus robuste
    tool_start = clean_response.find('{"tool"')
    if tool_start == -1:
        tool_start = clean_response.find('{ "tool"')
    
    if tool_start != -1:
        # Trouver la fin du JSON en comptant les accolades
        brace_count = 0
        json_end = -1
        for i in range(tool_start, len(clean_response)):
            if clean_response[i] == '{':
                brace_count += 1
            elif clean_response[i] == '}':
                brace_count -= 1
                if brace_count == 0:
                    json_end = i + 1
                    break
        
        if json_end != -1:
            try:
                json_str = clean_response[tool_start:json_end]
                data = json.loads(json_str)
                if "tool" in data:
                    return data
            except json.JSONDecodeError:
                pass
    
    # Stratégie C : Réponse courte qui COMMENCE par { (compatibilité)
    if clean_response.startswith('{') and len(clean_response) < 500:
        try:
            end_index = clean_response.rfind('}')
            if end_index != -1:
                json_str = clean_response[:end_index + 1]
                data = json.loads(json_str)
                if "tool" in data:
                    return data
        except Exception:
            pass
        
    return None

# === HELPERS CONTEXTE & SYSTÈME ===

def lire_fenetre() -> str:
    try:
        return FENETRE_ACTIVE.read_text(encoding='utf-8') if FENETRE_ACTIVE.exists() else ""
    except:
        return ""


def sauvegarder_fenetre(contenu: str):
    try:
        DATA_DIR.mkdir(exist_ok=True)
        FENETRE_ACTIVE.write_text(contenu, encoding='utf-8')
    except Exception as e:
        logger.error(f"Save error: {e}")


def consigner_interaction(user_msg: str, ai_msg: str) -> dict:
    """
    Consigne l'interaction dans la fenêtre active.
    Déclenche la rotation + Scribe batch si seuil atteint.
    """
    global _token_counter
    
    timestamp = get_timestamp_zulu()
    entry = f"\n[{timestamp}] User: {user_msg.strip()}\n[{timestamp}] Iris: {ai_msg.strip()}\n"
    
    if not validate_input_size(entry)[0]:
        return {"status": "error"}
    
    current = lire_fenetre()
    
    # Vérifier si rotation nécessaire
    if count_tokens(current + entry) > THRESHOLD:
        # Rotation de la fenêtre
        rotation_result = rotate_window(FENETRE_ACTIVE, BUFFER_DIR, ECHANGES_DIR)
        
        # NOUVEAU v0.10.2: Déclencher Scribe batch sur le fichier rotaté
        if rotation_result and rotation_result.get("status") == "success":
            rotated_file = rotation_result.get("archive")  # Clé du dict retourné par rotate_window()
            if rotated_file:
                logger.info(f"🖋️ Scribe batch déclenché sur: {rotated_file}")
                # Lancer en arrière-plan pour ne pas bloquer
                threading.Thread(
                    target=_process_rotated_file,
                    args=(rotated_file,),
                    daemon=True
                ).start()
        
        current = lire_fenetre()
        _token_counter = 0  # Reset compteur après rotation
        
    sauvegarder_fenetre(current + entry)
    
    # Mettre à jour compteur pour temps réel
    _token_counter += count_tokens(entry)
    
    return {"status": "success", "tokens_added": count_tokens(entry)}


def _process_rotated_file(file_path: str):
    """
    Traite un fichier rotaté avec Scribe batch (en arrière-plan).
    C'est ici que les gr_id sont correctement assignés par Clio.
    """
    try:
        scribe = get_scribe()
        result = scribe.segment_and_index(input_file=file_path)
        if result:
            logger.info(f"✅ Scribe batch terminé: {result.get('segments_created', 0)} segments, "
                       f"{result.get('segments_skipped', 0)} skippés")
    except Exception as e:
        logger.error(f"❌ Scribe batch erreur: {e}")


async def declencher_scribe_async(user: str, assistant: str):
    """
    Déclenche le Scribe en temps réel (segment par segment).
    NOTE: En temps réel, gr_id sera NULL car Clio traite un segment à la fois.
    Les gr_id corrects sont assignés lors du traitement batch après rotation.
    """
    global _token_counter, _scribe_insert_fn
    
    try:
        scribe = get_scribe()
        
        # Extraire métadonnées pour les deux messages
        meta = await scribe.extractor.extract_batch_async([user, assistant])
        
        if meta and len(meta) >= 2:
            ts = get_timestamp_zulu()
            
            # Utiliser la fonction d'insertion du Scribe (cohérente avec v4.1)
            if _scribe_insert_fn:
                # User message
                user_tokens = count_tokens(user)
                _scribe_insert_fn(ts, _token_counter, "human", meta[0])
                
                # Assistant message
                assistant_tokens = count_tokens(assistant)
                _scribe_insert_fn(ts, _token_counter + user_tokens, "assistant", meta[1])
                
                logger.info(f"🖋️ Scribe temps réel: 2 segments indexés (conf: {meta[0].get('confidence_score', '?')}, {meta[1].get('confidence_score', '?')})")
            
    except Exception as e:
        logger.error(f"Scribe realtime error: {e}")


# === APP FASTAPI ===
app = FastAPI(title="MOSS v0.10.2", version="0.10.2")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])


@app.get("/")
async def root():
    return {
        "system": "MOSS v0.10.2",
        "agent": "Iris (Gemini 3 Flash)",
        "mode": "Stabilisation - Scribe v4.1 intégré",
        "max_tool_chain": MAX_TOOL_CHAIN,
        "scribe_version": "4.1",
        "timestamp": get_timestamp_zulu()
    }


@app.get("/health")
async def health():
    return {"status": "ok", "version": "0.10.2"}


@app.post("/alterego")
async def alterego(request: Request):
    """
    Flux v0.10.2 avec chaînage d'outils + Scribe v4.1 :
    1. Iris reçoit la requête avec son contexte (system prompt + historique)
    2. Si elle a besoin de sa mémoire, elle génère un appel search_files
    3. Les résultats lui sont renvoyés pour synthèse
    4. Chaînage jusqu'à MAX_TOOL_CHAIN appels
    5. NOUVEAU: Scribe temps réel + batch après rotation
    """
    try:
        data = await request.json()
        message = data.get("message", "")
        
        # Lire la fenêtre complète (system prompt + historique)
        fenetre = lire_fenetre()
        
        # === LOG VISUEL : DÉBUT REQUÊTE ===
        timestamp_debut = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        logger.info("══" * 25)
        logger.info(f"📨 {timestamp_debut} | NOUVELLE REQUÊTE")
        logger.info("──" * 25)
        logger.info(f"💬 User: \"{message[:100]}{'...' if len(message) > 100 else ''}\"")
        
        # ══════════════════════════════════════════════════════════════
        # APPEL INITIAL : Iris analyse la demande (avec contexte complet)
        # ══════════════════════════════════════════════════════════════
        logger.info("🧠 Iris: Analyse demande...")
        reponse_courante = gemini.chat(message, context=fenetre)
        logger.info(f"📝 DEBUG reponse_init: {reponse_courante[:300] if reponse_courante else 'VIDE'}...")
        
        # Tracking des outils utilisés
        tools_used = []
        tool_results_context = ""  # Accumule les résultats pour le contexte
        
        # ══════════════════════════════════════════════════════════════
        # BOUCLE DE CHAÎNAGE : Jusqu'à MAX_TOOL_CHAIN appels d'outils
        # ══════════════════════════════════════════════════════════════
        tool_count = 0
        
        while tool_count < MAX_TOOL_CHAIN:
            tool_data = extract_tool_call(reponse_courante)
            
            # Pas d'appel d'outil détecté → réponse textuelle, on sort
            if not tool_data:
                break
                
            tool_name = tool_data.get("tool")
            
            # tool: null signifie qu'Iris répond directement
            if tool_name is None or tool_name == "null":
                break
            
            tool_args = tool_data.get("args", {})
            tool_count += 1
            tools_used.append(tool_name)
            
            logger.info(f"🔧 [{tool_count}/{MAX_TOOL_CHAIN}] Outil: {tool_name} | Args: {tool_args}")
            
            # Exécution via le Bibliothécaire (Hermès Wrapper)
            resultat_outil = dispatch_tool(tool_name, tool_args)
            
            # Log du résultat brut pour debug
            resultat_preview = resultat_outil[:500] if resultat_outil else 'VIDE'
            logger.info(f"📋 Résultat ({len(resultat_outil) if resultat_outil else 0} chars): {resultat_preview}...")
            
            # Accumuler les résultats dans le contexte
            tool_results_context += f"\n\n--- RÉSULTAT {tool_name} (query: {tool_args.get('query', '?')}) ---\n{resultat_outil}"
            
            # ══════════════════════════════════════════════════════════════
            # APPEL SUIVANT : Iris synthétise OU demande une autre recherche
            # ══════════════════════════════════════════════════════════════
            prompt_synthese = f"""DONNÉES COLLECTÉES:{tool_results_context}

REQUÊTE ORIGINALE DE SERGE : {message}

Si tu as assez d'informations, réponds à Serge.
Si tu as besoin d'une autre recherche, génère le JSON approprié.
Réponds :"""

            reponse_courante = gemini.chat(prompt_synthese, context=fenetre)
            logger.info(f"📝 DEBUG reponse_{tool_count}: {reponse_courante[:200] if reponse_courante else 'VIDE'}...")
        
        # Si on a atteint le max d'outils et la réponse est encore un JSON
        if tool_count >= MAX_TOOL_CHAIN and extract_tool_call(reponse_courante):
            logger.warning(f"⚠️ Max tool chain ({MAX_TOOL_CHAIN}) atteint, forçage synthèse")
            # Forcer une synthèse finale
            prompt_force = f"""DONNÉES COLLECTÉES:{tool_results_context}

REQUÊTE ORIGINALE DE SERGE : {message}

Tu as fait {tool_count} recherches. Synthétise maintenant ce que tu as trouvé et réponds à Serge.
NE GÉNÈRE PAS de nouveau JSON - réponds en texte."""

            reponse_courante = gemini.chat(prompt_force, context=fenetre)
        
        reponse_finale = reponse_courante
        
        # Consignation & Scribe
        consigner_interaction(message, reponse_finale)
        asyncio.create_task(declencher_scribe_async(message, reponse_finale))
        
        # === LOG VISUEL : FIN REQUÊTE ===
        timestamp_fin = datetime.now().strftime('%H:%M:%S')
        logger.info(f"🤖 Iris: \"{reponse_finale[:100]}{'...' if len(reponse_finale) > 100 else ''}\"")
        
        tools_summary = f" | Outils: {' → '.join(tools_used)}" if tools_used else ""
        logger.info(f"✅ {timestamp_fin} | Réponse ({len(reponse_finale)} chars){tools_summary}")
        logger.info("══" * 25)
        
        return {
            "message": reponse_finale,
            "metadata": {
                "tools_used": tools_used,
                "tool_count": len(tools_used),
                "version": "0.10.2"
            }
        }
        
    except Exception as e:
        logger.error(f"CRASH: {e}")
        logger.info("══" * 25)
        return JSONResponse(status_code=500, content={"error": str(e)})


@app.get("/status")
async def status():
    """Endpoint de statut détaillé pour debug."""
    window_status = get_window_status(FENETRE_ACTIVE)
    return {
        "version": "0.10.2",
        "scribe_version": "4.1",
        "window": window_status,
        "token_counter": _token_counter,
        "scribe_ready": _scribe_instance is not None,
        "timestamp": get_timestamp_zulu()
    }


if __name__ == "__main__":
    import uvicorn
    
    # Initialiser la fenêtre avec les instructions système
    print("📋 Initialisation fenêtre de contexte...")
    init_result = initialize_window(FENETRE_ACTIVE)
    if init_result["status"] == "success":
        print(f"   ✅ Instructions v{init_result.get('version', '?')} injectées ({init_result.get('tokens_instructions', 0)} tokens)")
    else:
        print(f"   ⭕ {init_result.get('reason', 'Déjà initialisé')}")
    
    # Pré-charger le Scribe pour éviter délai au premier message
    print("🖋️  Initialisation Scribe v4.1...")
    get_scribe()
    
    print("🕸️  Arachné: Réveil...")
    threading.Thread(target=arachne.main, daemon=True).start()
    
    print(f"🚀 MOSS v0.10.2 - Iris (chaînage max {MAX_TOOL_CHAIN} outils)")
    print(f"   📊 Scribe v4.1 intégré (gr_id + confidence_score)")
    print(f"   📁 Logs: {log_file}")
    uvicorn.run(app, host=HOST, port=PORT)
