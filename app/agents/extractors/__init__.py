"""
Extracteurs de métadonnées pour le Scribe.
"""
from .base import BaseExtractor
from .ollama_extractor import OllamaExtractor
from .ollama_extractor_parallel import OllamaParallelExtractor
from .vllm_extractor import VLLMExtractor
from .gemini_extractor import GeminiExtractor

# OpenAI est optionnel (nécessite le package openai)
try:
    from .openai_extractor import OpenAIExtractor
except ImportError:
    OpenAIExtractor = None

__all__ = [
    "BaseExtractor", 
    "OllamaExtractor", 
    "OllamaParallelExtractor",
    "OpenAIExtractor",
    "VLLMExtractor"
]