"""
llm_client.py - Abstraction LLM pour AIter Ego
Permet de switcher entre Ollama (local) et Azure OpenAI (production)
via une simple variable d'environnement.
"""

import httpx
import os
from typing import Optional

# Configuration par défaut
LLM_PROVIDER = os.environ.get("LLM_PROVIDER", "ollama")  # "ollama" ou "azure"
OLLAMA_BASE_URL = os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434")
OLLAMA_MODEL = os.environ.get("OLLAMA_MODEL", "mistral")

# Azure (pour plus tard)
AZURE_OPENAI_KEY = os.environ.get("AZURE_OPENAI_KEY", "")
AZURE_OPENAI_ENDPOINT = os.environ.get("AZURE_OPENAI_ENDPOINT", "")
AZURE_OPENAI_ENGINE = os.environ.get("AZURE_OPENAI_ENGINE", "gpt-4o")


async def generate(
    prompt: str,
    system_prompt: Optional[str] = None,
    model: Optional[str] = None,
    temperature: float = 0.7,
    max_tokens: int = 500
) -> dict:
    """
    Génère une réponse du LLM.
    
    Args:
        prompt: Le message de l'utilisateur
        system_prompt: Instructions système (personnalité de l'agent)
        model: Modèle à utiliser (override la config)
        temperature: Créativité (0-1)
        max_tokens: Longueur max de la réponse
    
    Returns:
        dict avec 'response' (texte) et 'metadata' (stats)
    """
    
    if LLM_PROVIDER == "ollama":
        return await _generate_ollama(prompt, system_prompt, model, temperature)
    elif LLM_PROVIDER == "azure":
        return await _generate_azure(prompt, system_prompt, model, temperature, max_tokens)
    else:
        raise ValueError(f"LLM_PROVIDER inconnu: {LLM_PROVIDER}")


async def _generate_ollama(
    prompt: str,
    system_prompt: Optional[str],
    model: Optional[str],
    temperature: float
) -> dict:
    """Appel à Ollama local."""
    
    model = model or OLLAMA_MODEL
    
    # Construire le prompt complet
    full_prompt = prompt
    if system_prompt:
        full_prompt = f"{system_prompt}\n\nUtilisateur: {prompt}"
    
    payload = {
        "model": model,
        "prompt": full_prompt,
        "stream": False,
        "options": {
            "temperature": temperature
        }
    }
    
    async with httpx.AsyncClient() as client:
        response = await client.post(
            f"{OLLAMA_BASE_URL}/api/generate",
            json=payload,
            timeout=60.0  # Les LLM peuvent être lents
        )
        response.raise_for_status()
        data = response.json()
    
    return {
        "response": data.get("response", ""),
        "metadata": {
            "model": model,
            "provider": "ollama",
            "total_duration_ms": data.get("total_duration", 0) / 1_000_000,
            "prompt_tokens": data.get("prompt_eval_count", 0),
            "completion_tokens": data.get("eval_count", 0)
        }
    }


async def _generate_azure(
    prompt: str,
    system_prompt: Optional[str],
    model: Optional[str],
    temperature: float,
    max_tokens: int
) -> dict:
    """Appel à Azure OpenAI (pour production)."""
    
    # À implémenter quand on migre vers Azure
    raise NotImplementedError("Azure OpenAI pas encore implémenté - utilise Ollama pour l'instant")


# Fonction synchrone pour tests rapides
def generate_sync(prompt: str, system_prompt: Optional[str] = None) -> str:
    """Version synchrone simple pour tests."""
    import asyncio
    result = asyncio.run(generate(prompt, system_prompt))
    return result["response"]


# Test rapide si exécuté directement
if __name__ == "__main__":
    print("Test de llm_client.py...")
    response = generate_sync("Dis bonjour en français")
    print(f"Réponse: {response}")