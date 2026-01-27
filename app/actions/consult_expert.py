"""
consult_expert.py - Outil de délégation vers modèles spécialisés (MoA)

Permet à Iris (Gemini Flash) de déléguer les tâches complexes ou historiques
à des modèles plus performants (Thinking, Pro) via un appel STATELESS.

L'expert ne reçoit QUE la query spécifique (et éventuellement des extraits 
de documents), mais PAS l'historique de bavardage récent d'Iris.

v1.0.0 - Architecture Mixture of Agents (MoA)
Date: 2026-01-20

Usage:
    from actions.consult_expert import consult_expert
    result = consult_expert(query="Analyse cette architecture", expertise="reasoning")
"""

import logging
from typing import Dict, Any, Optional
from pathlib import Path

# Import du provider Gemini existant
from utils.gemini_provider import GeminiProvider

logger = logging.getLogger(__name__)

# === MAPPING EXPERTISE → MODÈLE ===
# Ces modèles sont appelés de manière stateless (one-shot)
# Note: Éviter les modèles 2.0 (dépréciés le 31 mars 2026)
EXPERT_MODELS = {
    # Raisonnement profond, logique complexe, analyse multi-étapes
    "reasoning": "gemini-2.5-pro",
    
    # Stabilité factuelle, grande fenêtre pour contexte documentaire
    "historian": "gemini-2.5-pro",
    
    # Optimisé pour le code, architecture, debugging
    "coder": "gemini-2.5-flash",
}

# Modèle de fallback si expertise inconnue
DEFAULT_EXPERT_MODEL = "gemini-2.5-flash"

# Instructions système par type d'expertise
EXPERT_INSTRUCTIONS = {
    "reasoning": """Tu es un expert en raisonnement logique et analyse complexe.
Ta tâche : analyser rigoureusement la question posée.

MÉTHODE :
1. Décompose le problème en sous-parties
2. Analyse chaque partie de manière explicite
3. Montre ton raisonnement étape par étape
4. Identifie les ambiguïtés ou informations manquantes
5. Conclus avec une réponse claire et justifiée

Si tu n'as pas assez d'informations pour conclure, dis-le explicitement.
Ne fais JAMAIS d'hypothèses non fondées.""",

    "historian": """Tu es un expert historien chargé de vérifier des faits passés.
Ta tâche : fournir des informations factuelles et datées.

RÈGLES STRICTES :
1. Réponds UNIQUEMENT avec les informations que tu connais avec certitude
2. Si tu n'es pas sûr d'une date ou d'un fait, dis-le EXPLICITEMENT
3. Ne fais AUCUNE supposition - mieux vaut dire "je ne sais pas" que d'inventer
4. Cite tes sources de connaissance quand possible
5. Distingue clairement les faits des interprétations

IMPORTANT : Tu reçois parfois du contexte documentaire provenant de la mémoire
de l'utilisateur. Utilise-le comme source primaire d'information.""",

    "coder": """Tu es un expert en programmation Python et architecture logicielle.
Ta tâche : produire du code de qualité professionnelle.

STANDARDS :
1. Code propre, lisible, bien commenté
2. Gestion des erreurs appropriée
3. Typing hints quand pertinent
4. Docstrings pour les fonctions publiques
5. Explique brièvement les choix techniques si nécessaire

Si on te demande d'analyser du code existant :
- Identifie les problèmes potentiels
- Propose des améliorations concrètes
- Fournis des exemples de code corrigé""",
}


def consult_expert(
    query: str,
    expertise: str = "reasoning",
    context: Optional[str] = None
) -> Dict[str, Any]:
    """
    Consulte un modèle expert de manière STATELESS.
    
    L'expert ne reçoit QUE la query (et optionnellement du contexte documentaire),
    mais JAMAIS l'historique de bavardage récent d'Iris. Cela garantit une
    réponse non contaminée par la conversation en cours.
    
    Args:
        query: La question complexe ou historique à vérifier
        expertise: Type d'expert requis
            - 'reasoning' : Analyse complexe, logique profonde (Thinking model)
            - 'historian' : Vérification factuelle, dates, événements (Pro model)
            - 'coder' : Code, architecture, debugging (Flash exp)
        context: Contexte documentaire optionnel (extraits de mémoire, données trouvées)
                 ⚠️ NE PAS passer l'historique de conversation ici !
    
    Returns:
        dict avec:
            - status: "success" ou "error"
            - response: Réponse de l'expert
            - model_used: Modèle effectivement utilisé
            - expertise: Type d'expertise demandé
            - error: Message d'erreur si échec
    """
    # Validation des entrées
    if not query or not query.strip():
        return {
            "status": "error",
            "error": "Le paramètre 'query' est obligatoire et ne peut pas être vide",
            "expertise": expertise,
            "model_used": None
        }
    
    # 1. Sélectionner le modèle
    model = EXPERT_MODELS.get(expertise, DEFAULT_EXPERT_MODEL)
    
    if expertise not in EXPERT_MODELS:
        logger.warning(f"⚠️ Expertise inconnue '{expertise}', fallback vers {DEFAULT_EXPERT_MODEL}")
    
    logger.info(f"🎓 Consultation expert: {expertise} → {model}")
    logger.info(f"   Query: {query[:100]}{'...' if len(query) > 100 else ''}")
    if context:
        logger.info(f"   Contexte fourni: {len(context)} caractères")
    
    # 2. Récupérer les instructions système pour cette expertise
    system_instruction = EXPERT_INSTRUCTIONS.get(
        expertise, 
        "Tu es un expert consulté pour une question spécifique. Réponds de manière factuelle et précise."
    )
    
    # 3. Construire le message final (stateless - pas d'historique)
    message_parts = []
    
    # Instructions système en premier
    message_parts.append(system_instruction)
    message_parts.append("\n" + "="*50 + "\n")
    
    # Contexte documentaire si fourni
    if context and context.strip():
        message_parts.append("CONTEXTE DOCUMENTAIRE (données de la mémoire) :")
        message_parts.append("-" * 40)
        message_parts.append(context.strip())
        message_parts.append("-" * 40)
        message_parts.append("")
    
    # La question
    message_parts.append("QUESTION À ANALYSER :")
    message_parts.append(query.strip())
    
    full_message = "\n".join(message_parts)
    
    # 4. Instancier un provider TEMPORAIRE avec le bon modèle
    try:
        expert_provider = GeminiProvider(
            model=model, 
            enable_grounding=False  # Pas de web search pour les experts
        )
        
        # Appel one-shot : chat() sans historique, sans contexte conversationnel
        # C'est la clé du stateless - on ne passe PAS l'historique d'Iris
        response = expert_provider.chat(full_message)
        
        # Vérifier qu'on a une réponse valide
        if not response or not response.strip():
            logger.warning(f"⚠️ Réponse expert vide")
            return {
                "status": "error",
                "error": "L'expert a retourné une réponse vide",
                "model_used": model,
                "expertise": expertise
            }
        
        logger.info(f"✅ Réponse expert reçue ({len(response)} caractères)")
        
        return {
            "status": "success",
            "response": response,
            "model_used": model,
            "expertise": expertise
        }
        
    except Exception as e:
        logger.error(f"❌ Erreur consultation expert: {e}")
        import traceback
        traceback.print_exc()
        
        return {
            "status": "error",
            "error": str(e),
            "model_used": model,
            "expertise": expertise
        }


# === FONCTION UTILITAIRE POUR LE WRAPPER ===
def format_expert_response(result: Dict[str, Any]) -> str:
    """
    Formate la réponse de l'expert pour injection dans la réponse d'Iris.
    Utilisé par hermes_wrapper.py
    """
    if result.get("status") == "success":
        expertise = result.get("expertise", "unknown")
        model = result.get("model_used", "unknown")
        response = result.get("response", "")
        
        # En-tête discret pour traçabilité
        header = f"🎓 Analyse expert ({expertise}):\n"
        return header + response
    else:
        return f"Erreur consultation expert: {result.get('error', 'Erreur inconnue')}"


# === TEST ===
if __name__ == "__main__":
    import sys
    
    print("=" * 60)
    print("CONSULT_EXPERT v1.0.0 - Test Architecture MoA")
    print("=" * 60)
    
    # Vérifier que le provider Gemini est accessible
    try:
        from utils.gemini_provider import GeminiProvider
        print("✅ Import GeminiProvider réussi")
    except ImportError as e:
        print(f"❌ Erreur import: {e}")
        print("   Ce test doit être lancé depuis le dossier app/")
        sys.exit(1)
    
    # Test 1: Expertise reasoning
    print("\n" + "-" * 40)
    print("TEST 1: Expertise 'reasoning'")
    print("-" * 40)
    result = consult_expert(
        query="Si tous les A sont B, et certains B sont C, peut-on conclure que certains A sont C?",
        expertise="reasoning"
    )
    print(f"Status: {result['status']}")
    print(f"Modèle: {result['model_used']}")
    if result['status'] == 'success':
        print(f"Réponse (extrait): {result['response'][:300]}...")
    else:
        print(f"Erreur: {result.get('error')}")
    
    # Test 2: Expertise historian avec contexte
    print("\n" + "-" * 40)
    print("TEST 2: Expertise 'historian' avec contexte")
    print("-" * 40)
    result = consult_expert(
        query="Quand le projet MOSS a-t-il été créé d'après ce contexte?",
        expertise="historian",
        context="Extrait mémoire: Le 15 octobre 2024, Serge a mentionné démarrer un nouveau projet appelé MOSS pour la mémoire persistante."
    )
    print(f"Status: {result['status']}")
    print(f"Modèle: {result['model_used']}")
    if result['status'] == 'success':
        print(f"Réponse (extrait): {result['response'][:300]}...")
    else:
        print(f"Erreur: {result.get('error')}")
    
    # Test 3: Expertise coder
    print("\n" + "-" * 40)
    print("TEST 3: Expertise 'coder'")
    print("-" * 40)
    result = consult_expert(
        query="Écris une fonction Python pour calculer la similarité cosinus entre deux vecteurs",
        expertise="coder"
    )
    print(f"Status: {result['status']}")
    print(f"Modèle: {result['model_used']}")
    if result['status'] == 'success':
        print(f"Réponse (extrait): {result['response'][:500]}...")
    else:
        print(f"Erreur: {result.get('error')}")
    
    # Test 4: Expertise inconnue (fallback)
    print("\n" + "-" * 40)
    print("TEST 4: Expertise inconnue (test fallback)")
    print("-" * 40)
    result = consult_expert(
        query="Quelle est la capitale de la France?",
        expertise="geographe"  # N'existe pas
    )
    print(f"Status: {result['status']}")
    print(f"Modèle utilisé (fallback): {result['model_used']}")
    
    print("\n" + "=" * 60)
    print("Tests terminés!")
    print("=" * 60)
