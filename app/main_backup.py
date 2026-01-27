"""
main.py - AIter Ego / MOSS (Memory-Oriented Semantic System)
Point d'entrée du serveur local avec architecture hybride complète.

Version: 0.6.0
- Intégration Hermès (recherche sémantique locale)
- Intégration Gemini (Agent cloud via Google AI Studio)
- Intégration Scribe Gemini (indexation temps réel via API)
- Flux complet: User → MOSS → Hermès → Gemini → Scribe (async)
- Conservation des endpoints existants pour rétrocompatibilité
"""

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from datetime import datetime, timezone
from pathlib import Path
import logging
import importlib
import asyncio

from config import HOST, PORT, DATA_DIR, BUFFER_DIR
from utils.context_window import (
    count_tokens, 
    should_rotate, 
    rotate_window, 
    get_window_status,
    validate_input_size,
    process_large_input,
    THRESHOLD,
    MAX_INPUT
)

# === IMPORTS v0.5.0 ===
from actions.hermes import run as hermes_search
from utils.gemini_provider import GeminiProvider
from utils.query_profiler import QueryProfiler

# === IMPORTS v0.6.0 - SCRIBE GEMINI ===
from agents.scribe import Scribe

# === LOGGING ===
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# === FICHIERS ===
FENETRE_ACTIVE = DATA_DIR / "fenetre_active.txt"

# === GEMINI PROVIDER (singleton) ===
gemini = GeminiProvider()
query_profiler = QueryProfiler()

# === SCRIBE GEMINI (singleton) ===
# Instance globale initialisée au premier appel
_scribe_instance = None

def get_scribe() -> Scribe:
    """
    Retourne l'instance globale du Scribe (lazy initialization).
    Mode Gemini 2.5-flash-lite pour indexation rapide.
    """
    global _scribe_instance
    if _scribe_instance is None:
        _scribe_instance = Scribe(mode="gemini", parallel_batches=0, batch_size=2)
        logger.info("✨ Scribe Gemini initialisé (singleton)")
    return _scribe_instance


# === ACTIONS DISPONIBLES ===
ACTIONS_DISPONIBLES = {
    "read": {
        "description": "Lire le contenu d'un fichier",
        "params": ["fichier"],
        "exemple": {"fichier": "data/fenetre_active.txt"}
    },
    "write": {
        "description": "Écrire (ou réécrire) un fichier",
        "params": ["fichier", "contenu"],
        "exemple": {"fichier": "data/test.txt", "contenu": "Hello world!"}
    },
    "append": {
        "description": "Ajouter du contenu à la fin d'un fichier",
        "params": ["fichier", "contenu"],
        "exemple": {"fichier": "data/log.txt", "contenu": "Nouvelle entrée\n"}
    },
    "search": {
        "description": "Rechercher un mot dans un fichier",
        "params": ["fichier", "mot"],
        "exemple": {"fichier": "data/fenetre_active.txt", "mot": "MOSS"}
    },
    "listdir": {
        "description": "Lister les fichiers d'un dossier",
        "params": ["dossier"],
        "exemple": {"dossier": "buffer/"}
    },
    "hermes": {
        "description": "Recherche sémantique dans la mémoire (SQLite + tags Roget)",
        "params": ["query", "top_k"],
        "exemple": {"query": "Christian Gagné projet", "top_k": 5}
    }
}

# === APP ===
app = FastAPI(
    title="AIter Ego / MOSS",
    description="Memory-Oriented Semantic System - Architecture hybride Hermès + Gemini + Scribe",
    version="0.6.0"
)

# CORS pour accès depuis n'importe où
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# === HELPERS ===
def get_timestamp_zulu() -> str:
    """Retourne timestamp au format Zulu (UTC)."""
    return datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%S.%f')[:-3] + 'Z'


def lire_fenetre() -> str:
    """Lit la fenêtre de contexte active."""
    try:
        if FENETRE_ACTIVE.exists():
            return FENETRE_ACTIVE.read_text(encoding='utf-8')
        return ""
    except Exception as e:
        logger.error(f"Erreur lecture fenêtre: {e}")
        return ""


def sauvegarder_fenetre(contenu: str):
    """Sauvegarde la fenêtre de contexte active."""
    try:
        DATA_DIR.mkdir(exist_ok=True)
        FENETRE_ACTIVE.write_text(contenu, encoding='utf-8')
    except Exception as e:
        logger.error(f"Erreur sauvegarde fenêtre: {e}")


def consigner_interaction(message_user: str, message_assistant: str) -> dict:
    """
    Ajoute une interaction à la fenêtre avec horodatage.
    Gère les gros messages et la rotation automatique.
    
    Returns:
        dict avec infos sur le traitement
    """
    timestamp = get_timestamp_zulu()
    
    # Nouvelle ligne à ajouter
    nouvelle_ligne = f"\n[{timestamp}] Utilisateur : {message_user.strip()}\n[{timestamp}] AIter Ego : {message_assistant.strip()}\n"
    
    tokens_nouveau = count_tokens(nouvelle_ligne)
    
    # Vérifier si le message est trop volumineux (> 180K)
    is_valid, error = validate_input_size(nouvelle_ligne)
    if not is_valid:
        logger.error(f"❌ Message rejeté: {error}")
        return {"status": "error", "error": error}
    
    # Lire fenêtre actuelle
    fenetre_actuelle = lire_fenetre()
    tokens_actuels = count_tokens(fenetre_actuelle)
    
    # Cas 1: Message très volumineux (> 90K) - découper en chunks
    if tokens_nouveau > THRESHOLD:
        logger.info(f"📦 CHUNKING: Message de {tokens_nouveau} tokens (> {THRESHOLD})")
        result = process_large_input(nouvelle_ligne, FENETRE_ACTIVE, BUFFER_DIR)
        
        if result["status"] == "chunked":
            # Archiver la fenêtre actuelle d'abord
            if tokens_actuels > 0:
                rotate_result = rotate_window(FENETRE_ACTIVE, BUFFER_DIR)
                logger.info(f"   → Fenêtre actuelle archivée: {rotate_result.get('archive', 'N/A')}")
            
            # Les chunks sont déjà archivés, mettre le dernier dans la fenêtre
            sauvegarder_fenetre(result["active_chunk"])
            
            logger.info(f"   → {result['chunks_count']} chunks créés")
            logger.info(f"   → {len(result['archived'])} chunks archivés dans buffer")
            logger.info(f"   → {result['active_chunk_tokens']} tokens dans fenêtre active")
            
            return result
    
    # Cas 2: Rotation normale si nécessaire
    if should_rotate(tokens_actuels, tokens_nouveau):
        logger.info(f"🔄 ROTATION: {tokens_actuels} + {tokens_nouveau} > {THRESHOLD}")
        result = rotate_window(FENETRE_ACTIVE, BUFFER_DIR)
        logger.info(f"   → Archive: {result.get('archive', 'N/A')}")
        logger.info(f"   → Overlap: {result.get('tokens_overlap', 0)} tokens")
        
        # Relire la fenêtre (maintenant avec overlap seulement)
        fenetre_actuelle = lire_fenetre()
    
    # Cas 3: Ajout normal
    sauvegarder_fenetre(fenetre_actuelle + nouvelle_ligne)
    
    # Log du statut
    status = get_window_status(FENETRE_ACTIVE)
    logger.info(f"📊 Fenêtre: {status['tokens']} tokens ({status['usage_percent']}%)")
    
    return {"status": "success", "tokens_added": tokens_nouveau}


async def declencher_scribe_async(message_user: str, message_assistant: str):
    """
    Déclenche le Scribe en arrière-plan (fire & forget).
    Indexe l'échange dans SQLite via Gemini 2.5-flash-lite.
    
    Cette fonction est non-bloquante et n'impacte pas le temps de réponse.
    """
    try:
        scribe = get_scribe()
        timestamp = get_timestamp_zulu()
        
        # Extraction async des métadonnées pour les deux messages
        texts = [message_user, message_assistant]
        metadatas = await scribe.extractor.extract_batch_async(texts)
        
        # Insertion dans SQLite
        if metadatas and len(metadatas) >= 2:
            scribe._insert_metadata(
                timestamp=timestamp,
                token_start=0,
                source_file="realtime",
                source_origine="conversation",
                auteur="human",
                metadata=metadatas[0]
            )
            scribe._insert_metadata(
                timestamp=timestamp,
                token_start=0,
                source_file="realtime",
                source_origine="conversation",
                auteur="assistant",
                metadata=metadatas[1]
            )
            logger.info(f"✅ SCRIBE: 2 segments indexés")
        else:
            logger.warning(f"⚠️ SCRIBE: Métadonnées incomplètes")
        
    except Exception as e:
        logger.error(f"❌ Erreur Scribe async: {e}")


# === ROUTES PRINCIPALES ===

@app.get("/")
async def root():
    """Page d'accueil avec statut complet."""
    fenetre = get_window_status(FENETRE_ACTIVE)
    
    # Statut Hermès (SQLite)
    try:
        hermes_stats = hermes_search({"action": "stats"})
    except:
        hermes_stats = {"segments": 0}
    
    # Statut Scribe
    try:
        scribe = get_scribe()
        scribe_status = {
            "mode": scribe.mode,
            "model": scribe.extractor.model if hasattr(scribe, 'extractor') else "N/A"
        }
    except:
        scribe_status = {"mode": "non initialisé"}
    
    return {
        "message": "🧠 AIter Ego / MOSS fonctionne!",
        "version": "0.6.0",
        "architecture": "Hermès (local) + Gemini (cloud) + Scribe (async)",
        "timestamp": get_timestamp_zulu(),
        "agent": "Gemini 2.5 Flash",
        "scribe": scribe_status,
        "fenetre": fenetre,
        "hermes": {
            "segments": hermes_stats.get("total_segments", hermes_stats.get("segments", 0))
        },
        "actions_disponibles": len(ACTIONS_DISPONIBLES),
        "endpoints": {
            "conversation": "/alterego",
            "actions": "/go",
            "liste_actions": "/actions",
            "hermes_search": "/hermes",
            "scribe_status": "/scribe",
            "documentation": "/docs"
        }
    }


@app.get("/health")
async def health():
    """Health check."""
    return {"status": "ok", "timestamp": get_timestamp_zulu()}


# === ROUTES ACTIONS ===

@app.get("/actions")
async def liste_actions():
    """Liste toutes les actions disponibles."""
    return {
        "actions": ACTIONS_DISPONIBLES,
        "total": len(ACTIONS_DISPONIBLES),
        "timestamp": get_timestamp_zulu()
    }


@app.api_route("/go", methods=["GET", "POST"])
async def executer_action(request: Request):
    """
    Exécute une action spécifique.
    
    GET: /go?action=read&fichier=data/test.txt
    POST: {"action": "read", "fichier": "data/test.txt"}
    """
    # Récupérer les paramètres (GET ou POST)
    if request.method == "POST":
        try:
            params = await request.json()
        except:
            params = {}
    else:
        params = dict(request.query_params)
    
    action = params.get("action")
    
    if not action:
        return JSONResponse(
            status_code=400,
            content={
                "error": "Paramètre 'action' manquant",
                "actions_disponibles": list(ACTIONS_DISPONIBLES.keys()),
                "exemple": "/go?action=read&fichier=data/test.txt"
            }
        )
    
    if action not in ACTIONS_DISPONIBLES:
        return JSONResponse(
            status_code=404,
            content={
                "error": f"Action '{action}' inconnue",
                "actions_disponibles": list(ACTIONS_DISPONIBLES.keys())
            }
        )
    
    try:
        # Importer et exécuter l'action dynamiquement
        logger.info(f"⚡ Action: {action} avec params: {params}")
        module = importlib.import_module(f"actions.{action}")
        result = module.run(params)
        
        return {
            "action": action,
            "result": result,
            "timestamp": get_timestamp_zulu()
        }
        
    except Exception as e:
        logger.error(f"Erreur action {action}: {e}")
        return JSONResponse(
            status_code=500,
            content={
                "error": f"Erreur lors de l'exécution de '{action}': {str(e)}",
                "action": action,
                "timestamp": get_timestamp_zulu()
            }
        )


# === ROUTES HERMÈS ===

@app.api_route("/hermes", methods=["GET", "POST"])
async def hermes_endpoint(request: Request):
    """
    Recherche sémantique via Hermès.
    
    GET: /hermes?query=Christian+Gagné&top_k=5
    POST: {"query": "Christian Gagné", "top_k": 5}
    
    Actions disponibles:
    - query (défaut): Recherche par mots-clés
    - stats: Statistiques de la base
    - tags: Recherche par tags Roget
    - emotion: Recherche par état émotionnel
    """
    # Récupérer les paramètres
    if request.method == "POST":
        try:
            params = await request.json()
        except:
            params = {}
    else:
        params = dict(request.query_params)
    
    try:
        logger.info(f"🔍 Hermès: {params}")
        result = hermes_search(params)
        
        return {
            "hermes": result,
            "timestamp": get_timestamp_zulu()
        }
        
    except Exception as e:
        logger.error(f"Erreur Hermès: {e}")
        return JSONResponse(
            status_code=500,
            content={"error": f"Erreur Hermès: {str(e)}"}
        )


# === ROUTES SCRIBE (NOUVEAU v0.6.0) ===

@app.get("/scribe")
async def scribe_status():
    """Retourne le statut du Scribe."""
    try:
        scribe = get_scribe()
        return {
            "scribe": {
                "mode": scribe.mode,
                "model": scribe.extractor.model if hasattr(scribe, 'extractor') else "N/A",
                "batch_size": scribe.batch_size,
                "status": "ready"
            },
            "timestamp": get_timestamp_zulu()
        }
    except Exception as e:
        return JSONResponse(
            status_code=500,
            content={"error": f"Erreur Scribe: {str(e)}"}
        )


@app.post("/scribe/index")
async def scribe_index_manual(request: Request):
    """
    Indexation manuelle via le Scribe.
    
    POST: {"message_user": "...", "message_assistant": "..."}
    """
    try:
        data = await request.json()
        message_user = data.get("message_user", "")
        message_assistant = data.get("message_assistant", "")
        
        if not message_user or not message_assistant:
            return JSONResponse(
                status_code=400,
                content={"error": "Paramètres 'message_user' et 'message_assistant' requis"}
            )
        
        # Appel synchrone pour test manuel
        await declencher_scribe_async(message_user, message_assistant)
        
        return {
            "status": "indexed",
            "timestamp": get_timestamp_zulu()
        }
        
    except Exception as e:
        logger.error(f"Erreur indexation manuelle: {e}")
        return JSONResponse(
            status_code=500,
            content={"error": f"Erreur: {str(e)}"}
        )


# === ROUTES FENÊTRE DE CONTEXTE ===

@app.get("/fenetre")
async def fenetre_status():
    """Retourne le statut de la fenêtre de contexte."""
    status = get_window_status(FENETRE_ACTIVE)
    return {
        "fenetre": status,
        "seuil_rotation": THRESHOLD,
        "max_input": MAX_INPUT,
        "timestamp": get_timestamp_zulu()
    }


@app.get("/contexte")
async def get_contexte():
    """Retourne le contexte actuel (pour debug)."""
    contenu = lire_fenetre()
    return {
        "contexte": contenu,
        "tokens": count_tokens(contenu),
        "timestamp": get_timestamp_zulu()
    }


@app.delete("/contexte")
async def clear_contexte():
    """Efface le contexte (reset)."""
    sauvegarder_fenetre("")
    return {
        "message": "Contexte effacé",
        "timestamp": get_timestamp_zulu()
    }


@app.post("/rotation")
async def force_rotation():
    """Force une rotation manuelle (pour tests)."""
    result = rotate_window(FENETRE_ACTIVE, BUFFER_DIR)
    return {
        "rotation": result,
        "timestamp": get_timestamp_zulu()
    }


# === ROUTE CONVERSATION PRINCIPALE (REFONTE v0.6.0) ===

@app.post("/alterego")
async def alterego(request: Request):
    """
    Endpoint principal - Flux complet MOSS:
    1. User envoie message
    2. Hermès cherche contexte mémoire pertinent
    3. Gemini répond avec conscience du contexte
    4. Scribe indexe en arrière-plan (fire & forget)
    
    POST: {"message": "Bonjour, parle-moi de mon projet"}
    """
    logger.info("💬 Requête reçue sur /alterego")
    
    try:
        data = await request.json()
        message = data.get("message", "")
        
        if not message:
            return JSONResponse(
                status_code=400,
                content={"error": "Paramètre 'message' manquant"}
            )
        
        # Vérifier la taille du message AVANT traitement
        is_valid, error = validate_input_size(message)
        if not is_valid:
            logger.error(f"❌ Message rejeté: {error}")
            return JSONResponse(
                status_code=413,
                content={"error": error}
            )
        
        # === ÉTAPE 1: QueryProfiler analyse l'intention ===
        logger.info("🎯 PROFILER: Analyse de l'intention...")
        try:
            profile = query_profiler.analyze(message)
            logger.info(f"   → Intent: {profile.intent} (confiance: {profile.confidence:.0%})")
            logger.info(f"   → Weights: {profile.weights}")
            logger.info(f"   → Filters: {profile.filters}")
        except Exception as e:
            logger.warning(f"⚠️ Profiler indisponible: {e}")
            profile = None

        # === ÉTAPE 2: Hermès cherche le contexte mémoire ===
        logger.info("🔍 HERMÈS: Recherche contexte mémoire...")
        try:
            hermes_result = hermes_search({
                "query": message,
                "top_k": 5,
                "profile": profile
            })
            contexte_memoire = hermes_result.get("formatted_context", "")
            hermes_segments = hermes_result.get("count", 0)
            logger.info(f"   → {hermes_segments} segments trouvés")
        except Exception as e:
            logger.warning(f"⚠️ Hermès indisponible: {e}")
            contexte_memoire = ""
            hermes_segments = 0
        
        # Contexte de la fenêtre active (court terme)
        fenetre_active = lire_fenetre()
        contexte_recent = fenetre_active[-5000:] if fenetre_active else ""
        
        # === ÉTAPE 3: Gemini répond avec le contexte ===
        logger.info("🤖 GEMINI: Génération de la réponse...")
        try:
            # Combiner contexte mémoire (Hermès) + contexte récent (fenêtre)
            contexte_complet = ""
            if contexte_memoire:
                contexte_complet += f"=== MÉMOIRE PERTINENTE ===\n{contexte_memoire}\n\n"
            if contexte_recent:
                contexte_complet += f"=== CONVERSATION RÉCENTE ===\n{contexte_recent}\n"
            
            reponse = gemini.chat(message, context=contexte_complet if contexte_complet else None)
            logger.info(f"   → Réponse générée ({len(reponse)} caractères)")
            
        except Exception as e:
            logger.error(f"❌ Erreur Gemini: {e}")
            return JSONResponse(
                status_code=503,
                content={"error": f"Erreur Agent Gemini: {str(e)}"}
            )
        
        # === ÉTAPE 4: Consigner l'interaction ===
        consign_result = consigner_interaction(message, reponse)
        
        if consign_result.get("status") == "error":
            logger.warning(f"⚠️ Erreur consignation: {consign_result.get('error')}")
        
        # === ÉTAPE 5: Scribe en arrière-plan (fire & forget) ===
        asyncio.create_task(declencher_scribe_async(message, reponse))
        
        # Récupérer statut fenêtre pour metadata
        fenetre = get_window_status(FENETRE_ACTIVE)
        
        return {
            "message": reponse,
            "timestamp": get_timestamp_zulu(),
            "metadata": {
                "agent": "gemini-2.5-flash",
                "scribe": "gemini-2.5-flash-lite",
                "hermes_segments": hermes_segments,
                "contexte_injecte": bool(contexte_complet)
            },
            "fenetre": fenetre,
            "consignation": consign_result.get("status", "success")
        }
        
    except Exception as e:
        logger.error(f"Erreur /alterego: {e}")
        return JSONResponse(
            status_code=500,
            content={"error": f"Erreur interne: {str(e)}"}
        )


# === ROUTE CONVERSATION LEGACY (Ollama) ===

@app.post("/alterego-legacy")
async def alterego_legacy(request: Request):
    """
    Endpoint legacy - utilise Ollama au lieu de Gemini.
    Pour tests ou fallback si Gemini indisponible.
    """
    from utils.llm_client import generate
    
    logger.info("💬 Requête reçue sur /alterego-legacy (Ollama)")
    
    try:
        data = await request.json()
        message = data.get("message", "")
        
        if not message:
            return JSONResponse(
                status_code=400,
                content={"error": "Paramètre 'message' manquant"}
            )
        
        # Lire le contexte existant
        contexte = lire_fenetre()
        
        # Construire le system prompt
        system_prompt = f"""Tu es AIter Ego, un assistant personnel avec mémoire persistante.

Voici ta mémoire contextuelle (conversations précédentes):
---
{contexte[-10000:] if contexte else "(Aucun historique)"}
---

Instructions:
- Utilise ce contexte pour personnaliser tes réponses
- Sois concis mais utile
- Réponds en français
"""
        
        # Appeler Ollama
        result = await generate(
            prompt=message,
            system_prompt=system_prompt,
            temperature=0.7
        )
        
        reponse = result["response"]
        
        # Consigner l'interaction
        consign_result = consigner_interaction(message, reponse)
        
        fenetre = get_window_status(FENETRE_ACTIVE)
        
        return {
            "message": reponse,
            "timestamp": get_timestamp_zulu(),
            "metadata": result.get("metadata", {}),
            "fenetre": fenetre,
            "consignation": consign_result.get("status", "success"),
            "backend": "ollama"
        }
        
    except Exception as e:
        logger.error(f"Erreur /alterego-legacy: {e}")
        return JSONResponse(
            status_code=500,
            content={"error": f"Erreur interne: {str(e)}"}
        )


# === ROUTES UTILITAIRES ===

@app.get("/horodatage")
async def horodatage():
    """Retourne l'horodatage actuel."""
    now = datetime.now(timezone.utc)
    return {
        "timestamp_utc": now.isoformat(timespec='milliseconds'),
        "timestamp_zulu": get_timestamp_zulu()
    }


@app.get("/buffer")
async def buffer_status():
    """Retourne le contenu du buffer."""
    try:
        from actions.listdir import run as listdir_run
        result = listdir_run({"dossier": "buffer/"})
        return {
            "buffer": result,
            "timestamp": get_timestamp_zulu()
        }
    except Exception as e:
        return JSONResponse(
            status_code=500,
            content={"error": f"Erreur: {str(e)}"}
        )


# === DÉMARRAGE ===
if __name__ == "__main__":
    import uvicorn
    
    print("=" * 60)
    print("🧠 AIter Ego / MOSS v0.6.0")
    print("   Memory-Oriented Semantic System")
    print("=" * 60)
    print(f"🏗️  Architecture: Hermès (local) + Gemini (cloud) + Scribe (async)")
    print(f"🔍 Hermès: Recherche sémantique SQLite + tags Roget")
    print(f"🤖 Agent: Gemini 2.5 Flash (Google AI Studio)")
    print(f"📝 Scribe: Gemini 2.5 Flash Lite (indexation temps réel)")
    print("=" * 60)
    print(f"🚀 Serveur: http://{HOST}:{PORT}")
    print(f"📚 Documentation: http://{HOST}:{PORT}/docs")
    print(f"📊 Fenêtre de contexte: {THRESHOLD:,} tokens max")
    print(f"📦 Input maximum: {MAX_INPUT:,} tokens")
    print(f"⚡ Actions disponibles: {len(ACTIONS_DISPONIBLES)}")
    print("=" * 60)
    
    uvicorn.run(app, host=HOST, port=PORT)