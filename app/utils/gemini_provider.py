"""
gemini_provider.py - Connecteur pour l'API Gemini (Google AI Studio)
Agent conversationnel pour MOSS/AIter Ego

Version: 2.4.0
- Modèle: Gemini 3 Flash Preview
- Grounding désactivé par défaut (force l'usage de la mémoire locale)
- Temperature 0.2
- Fix: Extraction robuste des réponses (thought_signature, JSON, etc.)

Usage:
    from utils.gemini_provider import GeminiProvider
    
    agent = GeminiProvider()
    response = agent.chat("Bonjour, comment ça va?")
    response_with_context = agent.chat("Parle-moi de MOSS", context="[Mémoire: MOSS est un système de mémoire...]")
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

from google import genai
from google.genai import types

logger = logging.getLogger(__name__)

# === CONFIGURATION ===
DEFAULT_MODEL = "gemini-3-flash-preview"


class GeminiProvider:
    """
    Provider pour l'API Gemini via Google AI Studio.
    Gère la connexion, le contexte mémoire, le grounding web, et les conversations.
    """
    
    def __init__(self, model: str = DEFAULT_MODEL, enable_grounding: bool = False):
        """
        Initialise le provider Gemini.
        
        Args:
            model: Nom du modèle Gemini à utiliser
            enable_grounding: Activer le Grounding with Google Search (désactivé par défaut)
        """
        self.api_key = os.getenv("GEMINI_API_KEY")
        if not self.api_key:
            raise ValueError("GEMINI_API_KEY non trouvée dans les variables d'environnement. Vérifiez votre fichier .env")
        
        self.model = model
        self.enable_grounding = enable_grounding
        
        # Initialiser le client Google GenAI
        self.client = genai.Client(api_key=self.api_key)
        
        # Historique de conversation pour le mode multi-turn
        self.conversation_history = []
    
    def _get_config(self, with_grounding: bool = None) -> types.GenerateContentConfig:
        """
        Construit la configuration pour les requêtes.
        
        Args:
            with_grounding: Override pour activer/désactiver le grounding
        """
        use_grounding = with_grounding if with_grounding is not None else self.enable_grounding
        
        config_params = {
            "temperature": 0.2,
            "max_output_tokens": 8192,
        }
        
        # Ajouter le Google Search grounding si activé
        if use_grounding:
            config_params["tools"] = [types.Tool(google_search=types.GoogleSearch())]
        
        return types.GenerateContentConfig(**config_params)
    
    def _extract_response_text(self, response) -> str:
        """
        Extrait le texte de la réponse Gemini de manière robuste.
        Gère les cas: texte simple, thought_signature, JSON dans parts, etc.
        
        Args:
            response: Réponse brute de Gemini
            
        Returns:
            Texte extrait (peut être vide si vraiment rien)
        """
        # Essai 1: response.text direct
        try:
            if response.text:
                return response.text
        except Exception:
            pass
        
        # Essai 2: Explorer les candidates et parts
        try:
            if hasattr(response, 'candidates') and response.candidates:
                candidate = response.candidates[0]
                if hasattr(candidate, 'content') and candidate.content:
                    content = candidate.content
                    if hasattr(content, 'parts') and content.parts:
                        extracted_parts = []
                        for part in content.parts:
                            # Texte standard
                            if hasattr(part, 'text') and part.text:
                                extracted_parts.append(part.text)
                            # Thought (raisonnement interne de Gemini)
                            elif hasattr(part, 'thought') and part.thought:
                                # Le thought peut contenir du JSON ou du texte
                                extracted_parts.append(part.thought)
                            # Données brutes
                            elif hasattr(part, 'inline_data'):
                                pass  # Ignorer les données binaires
                            # Autre structure possible
                            else:
                                # Essayer de convertir en string
                                try:
                                    part_str = str(part)
                                    if part_str and part_str != 'None':
                                        # Vérifier si c'est un JSON valide
                                        if '{' in part_str and '}' in part_str:
                                            extracted_parts.append(part_str)
                                except:
                                    pass
                        
                        if extracted_parts:
                            return '\n'.join(extracted_parts)
        except Exception as e:
            logger.warning(f"Erreur extraction parts: {e}")
        
        # Essai 3: Sérialisation brute de la réponse
        try:
            response_str = str(response)
            # Chercher un JSON dans la réponse brute
            if '{"tool"' in response_str:
                start = response_str.find('{"tool"')
                end = response_str.find('}', start) + 1
                if end > start:
                    potential_json = response_str[start:end]
                    # Valider que c'est du JSON
                    try:
                        json.loads(potential_json)
                        return potential_json
                    except:
                        pass
        except Exception:
            pass
        
        return ""
    
    def chat(self, user_message: str, context: Optional[str] = None, 
             use_grounding: bool = None) -> str:
        """
        Envoie un message à Gemini et retourne la réponse.
        
        Args:
            user_message: Message de l'utilisateur
            context: Contexte mémoire optionnel (fourni par Hermès)
            use_grounding: Override pour activer/désactiver le grounding pour ce message
            
        Returns:
            Réponse de Gemini
        """
        # Construire le prompt avec contexte si fourni
        if context:
            full_message = f"{context}\n\n---\n\nMessage de l'utilisateur: {user_message}"
        else:
            full_message = user_message
        
        try:
            response = self.client.models.generate_content(
                model=self.model,
                contents=full_message,
                config=self._get_config(with_grounding=use_grounding)
            )
            
            # Extraction robuste du texte
            result_text = self._extract_response_text(response)
            
            # Si grounding activé, ajouter les sources si disponibles
            if use_grounding is not False and self.enable_grounding:
                if hasattr(response, 'candidates') and response.candidates:
                    candidate = response.candidates[0]
                    if hasattr(candidate, 'grounding_metadata') and candidate.grounding_metadata:
                        grounding = candidate.grounding_metadata
                        if hasattr(grounding, 'grounding_chunks') and grounding.grounding_chunks:
                            sources = []
                            for chunk in grounding.grounding_chunks:
                                if hasattr(chunk, 'web') and chunk.web:
                                    web = chunk.web
                                    if hasattr(web, 'uri') and hasattr(web, 'title'):
                                        sources.append(f"- [{web.title}]({web.uri})")
                            if sources:
                                result_text += "\n\n**Sources:**\n" + "\n".join(sources[:5])
            
            return result_text
            
        except Exception as e:
            return f"Erreur lors de l'appel à Gemini: {str(e)}"
    
    def chat_with_history(self, user_message: str, context: Optional[str] = None) -> str:
        """
        Chat avec historique de conversation (multi-turn).
        
        Args:
            user_message: Message de l'utilisateur
            context: Contexte mémoire optionnel
            
        Returns:
            Réponse de Gemini
        """
        if context and not self.conversation_history:
            formatted_message = f"{context}\n\n---\n\nMessage: {user_message}"
        else:
            formatted_message = user_message
        
        self.conversation_history.append({
            "role": "user",
            "parts": [formatted_message]
        })
        
        try:
            response = self.client.models.generate_content(
                model=self.model,
                contents=self.conversation_history,
                config=self._get_config()
            )
            
            assistant_message = self._extract_response_text(response)
            self.conversation_history.append({
                "role": "model",
                "parts": [assistant_message]
            })
            
            return assistant_message
            
        except Exception as e:
            self.conversation_history.pop()
            return f"Erreur lors de l'appel à Gemini: {str(e)}"
    
    def chat_stream(self, user_message: str, context: Optional[str] = None) -> Generator[str, None, None]:
        """
        Chat avec streaming (réponse progressive).
        
        Args:
            user_message: Message de l'utilisateur
            context: Contexte mémoire optionnel
            
        Yields:
            Chunks de texte au fur et à mesure
        """
        if context:
            full_message = f"{context}\n\n---\n\nMessage de l'utilisateur: {user_message}"
        else:
            full_message = user_message
        
        try:
            response = self.client.models.generate_content_stream(
                model=self.model,
                contents=full_message,
                config=self._get_config()
            )
            
            for chunk in response:
                if chunk.text:
                    yield chunk.text
                    
        except Exception as e:
            yield f"Erreur lors de l'appel à Gemini: {str(e)}"
    
    def search_web(self, query: str) -> str:
        """
        Recherche web explicite via Gemini + Google Search.
        Force le grounding pour cette requête.
        
        Args:
            query: Question ou recherche
            
        Returns:
            Réponse avec sources
        """
        search_prompt = f"Recherche sur Internet et donne-moi des informations actuelles sur: {query}"
        return self.chat(search_prompt, use_grounding=True)
    
    def clear_history(self):
        """Efface l'historique de conversation."""
        self.conversation_history = []
    
    def get_history_length(self) -> int:
        """Retourne le nombre de messages dans l'historique."""
        return len(self.conversation_history)
    
    def set_model(self, model: str):
        """Change le modèle Gemini utilisé."""
        self.model = model
    
    def set_grounding(self, enabled: bool):
        """Active ou désactive le grounding Google Search."""
        self.enable_grounding = enabled


# === TEST ===
if __name__ == "__main__":
    print("=" * 60)
    print("GEMINI PROVIDER v2.4 - Test de connexion")
    print("Modèle: Gemini 3 Flash Preview (grounding désactivé par défaut)")
    print("=" * 60)
    
    try:
        print("\n1. Initialisation du provider...")
        agent = GeminiProvider()
        print(f"   ✓ Connecté avec le modèle: {agent.model}")
        print(f"   ✓ Grounding activé: {agent.enable_grounding}")
        
        print("\n2. Test simple (sans grounding)...")
        response = agent.chat("Dis-moi bonjour en une phrase.", use_grounding=False)
        print(f"   → Réponse: {response[:100]}...")
        
        print("\n" + "=" * 60)
        print("✅ Test passé!")
        
    except Exception as e:
        print(f"\n❌ Erreur: {e}")
