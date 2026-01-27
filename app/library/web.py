"""
web.py - Recherche web explicite via Gemini + Google Search
Module de la bibliothèque MOSS/AIter Ego

Version: 1.0.0
- Permet à l'Agent de faire une recherche web CONSCIENTE
- Force le grounding pour cette requête uniquement
- Formate les résultats avec sources

Usage:
    from library.web import search_web
    result = search_web("dernières nouvelles IA décembre 2025")
"""

import os
import logging
from pathlib import Path
from dotenv import load_dotenv

# Charger les variables d'environnement
env_path = Path(__file__).parent.parent.parent / ".env"
load_dotenv(env_path)

from google import genai
from google.genai import types

logger = logging.getLogger(__name__)

# Configuration
SEARCH_MODEL = "gemini-3-flash-preview"  # Modèle pour les recherches web


def search_web(query: str, limit: int = 5) -> str:
    """
    Recherche web explicite via Gemini + Google Search.
    Force le grounding pour obtenir des informations actuelles.
    
    Args:
        query: La question ou recherche à effectuer
        limit: Nombre maximum de sources à retourner (défaut: 5)
        
    Returns:
        Texte formaté avec la réponse et les sources
    """
    logger.info(f"🌐 Recherche web: {query}")
    
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        return "Erreur: Clé API Gemini non configurée"
    
    try:
        client = genai.Client(api_key=api_key)
        
        # Configuration avec grounding forcé
        config = types.GenerateContentConfig(
            system_instruction="Tu es un assistant de recherche. Réponds de façon concise et factuelle en français. Cite tes sources.",
            temperature=0.7,
            max_output_tokens=2048,
            tools=[types.Tool(google_search=types.GoogleSearch())]
        )
        
        # Prompt optimisé pour la recherche
        search_prompt = f"Recherche des informations actuelles et fiables sur: {query}"
        
        response = client.models.generate_content(
            model=SEARCH_MODEL,
            contents=search_prompt,
            config=config
        )
        
        # Extraire le texte
        result_text = response.text if response.text else "Aucun résultat trouvé."
        
        # Extraire et formater les sources
        sources = []
        if hasattr(response, 'candidates') and response.candidates:
            candidate = response.candidates[0]
            if hasattr(candidate, 'grounding_metadata') and candidate.grounding_metadata:
                grounding = candidate.grounding_metadata
                if hasattr(grounding, 'grounding_chunks') and grounding.grounding_chunks:
                    for chunk in grounding.grounding_chunks[:limit]:
                        if hasattr(chunk, 'web') and chunk.web:
                            web = chunk.web
                            if hasattr(web, 'uri') and hasattr(web, 'title'):
                                sources.append(f"• {web.title}\n  {web.uri}")
        
        # Formater la réponse finale
        formatted_result = f"📡 RÉSULTATS WEB pour: {query}\n\n{result_text}"
        
        if sources:
            formatted_result += "\n\n📚 SOURCES:\n" + "\n".join(sources)
        
        logger.info(f"✅ Recherche web terminée: {len(sources)} sources trouvées")
        return formatted_result
        
    except Exception as e:
        error_msg = f"Erreur recherche web: {str(e)}"
        logger.error(error_msg)
        return error_msg


# === TEST ===
if __name__ == "__main__":
    print("=" * 60)
    print("TEST - Module web.py")
    print("=" * 60)
    
    test_query = "dernières nouvelles intelligence artificielle décembre 2025"
    print(f"\nRecherche: {test_query}\n")
    
    result = search_web(test_query)
    print(result)