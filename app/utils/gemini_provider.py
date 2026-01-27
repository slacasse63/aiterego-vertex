"""
gemini_provider.py - Connecteur pour l'API Gemini (Vertex AI / Google AI Studio)
Agent conversationnel pour MOSS/AIter Ego

Version: 3.0.0
- Support Vertex AI (production) ET Google AI Studio (legacy)
- Modele: Gemini 3 Flash Preview
- Grounding desactive par defaut
- Temperature 0.2

Configuration via .env:
    GEMINI_BACKEND=vertex    # ou "aistudio" pour Google AI Studio
    GOOGLE_CLOUD_PROJECT=gen-lang-client-0335807696  # pour Vertex
    GEMINI_API_KEY=xxx       # pour AI Studio uniquement
"""

import os
import json
import logging
from pathlib import Path
from typing import Optional, Generator
from dotenv import load_dotenv

# Charger les variables d'environnement depuis .env
env_path = Path(__file__).parent.parent.parent / ".env"
load_dotenv(env_path)

logger = logging.getLogger(__name__)

# === CONFIGURATION ===
DEFAULT_MODEL = "gemini-3-flash-preview"
VERTEX_LOCATION = "global"

# Detecter le backend a utiliser
BACKEND = os.getenv("GEMINI_BACKEND", "vertex").lower()

if BACKEND == "vertex":
    import vertexai
    from vertexai.generative_models import GenerativeModel, GenerationConfig
    PROJECT_ID = os.getenv("GOOGLE_CLOUD_PROJECT", "gen-lang-client-0335807696")
    vertexai.init(project=PROJECT_ID, location=VERTEX_LOCATION)
    logger.info(f"GeminiProvider: Backend Vertex AI initialise (projet: {PROJECT_ID})")
else:
    from google import genai
    from google.genai import types
    logger.info("GeminiProvider: Backend Google AI Studio initialise")


class GeminiProvider:
    """
    Provider pour l'API Gemini via Vertex AI ou Google AI Studio.
    """
    
    def __init__(self, model: str = DEFAULT_MODEL, enable_grounding: bool = False):
        self.model = model
        self.enable_grounding = enable_grounding
        self.backend = BACKEND
        
        if self.backend == "vertex":
            self.client = GenerativeModel(self.model)
        else:
            self.api_key = os.getenv("GEMINI_API_KEY")
            if not self.api_key:
                raise ValueError("GEMINI_API_KEY non trouvee dans les variables d'environnement")
            self.client = genai.Client(api_key=self.api_key)
        
        self.conversation_history = []
    
    def _get_generation_config(self) -> dict:
        return {
            "temperature": 0.2,
            "max_output_tokens": 8192,
        }
    
    def _extract_response_text(self, response) -> str:
        try:
            if response.text:
                return response.text
        except Exception:
            pass
        
        try:
            if hasattr(response, 'candidates') and response.candidates:
                candidate = response.candidates[0]
                if hasattr(candidate, 'content') and candidate.content:
                    content = candidate.content
                    if hasattr(content, 'parts') and content.parts:
                        extracted_parts = []
                        for part in content.parts:
                            if hasattr(part, 'text') and part.text:
                                extracted_parts.append(part.text)
                            elif hasattr(part, 'thought') and part.thought:
                                extracted_parts.append(part.thought)
                        if extracted_parts:
                            return '\n'.join(extracted_parts)
        except Exception as e:
            logger.warning(f"Erreur extraction parts: {e}")
        
        return ""
    
    def chat(self, user_message: str, context: Optional[str] = None, 
             use_grounding: bool = None) -> str:
        if context:
            full_message = f"{context}\n\n---\n\nMessage de l'utilisateur: {user_message}"
        else:
            full_message = user_message
        
        try:
            if self.backend == "vertex":
                generation_config = GenerationConfig(**self._get_generation_config())
                response = self.client.generate_content(
                    full_message,
                    generation_config=generation_config
                )
            else:
                config = types.GenerateContentConfig(**self._get_generation_config())
                if use_grounding or (use_grounding is None and self.enable_grounding):
                    config.tools = [types.Tool(google_search=types.GoogleSearch())]
                
                response = self.client.models.generate_content(
                    model=self.model,
                    contents=full_message,
                    config=config
                )
            
            return self._extract_response_text(response)
            
        except Exception as e:
            logger.error(f"Erreur Gemini: {e}")
            return f"Erreur lors de l'appel a Gemini: {str(e)}"
    
    def chat_with_history(self, user_message: str, context: Optional[str] = None) -> str:
        if context and not self.conversation_history:
            formatted_message = f"{context}\n\n---\n\nMessage: {user_message}"
        else:
            formatted_message = user_message
        
        self.conversation_history.append({
            "role": "user",
            "parts": [formatted_message]
        })
        
        try:
            if self.backend == "vertex":
                chat = self.client.start_chat(history=self.conversation_history[:-1])
                response = chat.send_message(formatted_message)
            else:
                response = self.client.models.generate_content(
                    model=self.model,
                    contents=self.conversation_history,
                    config=types.GenerateContentConfig(**self._get_generation_config())
                )
            
            assistant_message = self._extract_response_text(response)
            self.conversation_history.append({
                "role": "model",
                "parts": [assistant_message]
            })
            
            return assistant_message
            
        except Exception as e:
            self.conversation_history.pop()
            return f"Erreur lors de l'appel a Gemini: {str(e)}"
    
    def chat_stream(self, user_message: str, context: Optional[str] = None) -> Generator[str, None, None]:
        if context:
            full_message = f"{context}\n\n---\n\nMessage de l'utilisateur: {user_message}"
        else:
            full_message = user_message
        
        try:
            if self.backend == "vertex":
                response = self.client.generate_content(
                    full_message,
                    generation_config=GenerationConfig(**self._get_generation_config()),
                    stream=True
                )
            else:
                response = self.client.models.generate_content_stream(
                    model=self.model,
                    contents=full_message,
                    config=types.GenerateContentConfig(**self._get_generation_config())
                )
            
            for chunk in response:
                if chunk.text:
                    yield chunk.text
                    
        except Exception as e:
            yield f"Erreur lors de l'appel a Gemini: {str(e)}"
    
    def search_web(self, query: str) -> str:
        if self.backend == "vertex":
            return self.chat(f"Recherche des informations actuelles sur: {query}")
        else:
            search_prompt = f"Recherche sur Internet: {query}"
            return self.chat(search_prompt, use_grounding=True)
    
    def clear_history(self):
        self.conversation_history = []
    
    def get_history_length(self) -> int:
        return len(self.conversation_history)
    
    def set_model(self, model: str):
        self.model = model
        if self.backend == "vertex":
            self.client = GenerativeModel(self.model)
    
    def set_grounding(self, enabled: bool):
        self.enable_grounding = enabled


if __name__ == "__main__":
    print("=" * 60)
    print("GEMINI PROVIDER v3.0 - Test de connexion")
    print(f"Backend: {BACKEND.upper()}")
    print(f"Modele: {DEFAULT_MODEL}")
    print("=" * 60)
    
    try:
        print("\n1. Initialisation du provider...")
        agent = GeminiProvider()
        print(f"   OK - Connecte avec le modele: {agent.model}")
        print(f"   OK - Backend: {agent.backend}")
        
        print("\n2. Test simple...")
        response = agent.chat("Dis-moi bonjour en une phrase.")
        print(f"   Reponse: {response[:100]}...")
        
        print("\n" + "=" * 60)
        print("Test passe!")
        
    except Exception as e:
        print(f"\nErreur: {e}")
        import traceback
        traceback.print_exc()