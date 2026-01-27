import json
import re
import asyncio
import httpx
from typing import List, Dict
from .base import BaseExtractor

OLLAMA_URL = "http://localhost:11434/api/generate"
OLLAMA_MODEL = "mistral-nemo"

class OllamaParallelExtractor(BaseExtractor):
    
    def __init__(self, model: str = OLLAMA_MODEL, url: str = OLLAMA_URL, max_concurrent: int = 4):
        self.model = model
        self.url = url
        self.max_concurrent = max_concurrent
    
    def extract(self, text: str) -> Dict:
        """Extraction synchrone (single)"""
        return asyncio.run(self._extract_async(text))
    
    async def _extract_async(self, text: str) -> Dict:
        """Extraction asynchrone d'un seul texte"""
        text_sample = text[:3000] if len(text) > 3000 else text
        prompt = self._build_prompt(text_sample)
        
        try:
            async with httpx.AsyncClient(timeout=300.0) as client:
                response = await client.post(
                    self.url,
                    json={"model": self.model, "prompt": prompt, "stream": False}
                )
                
                if response.status_code == 200:
                    result = response.json()
                    return self._parse_response(result.get("response", ""))
                return self.default_metadata()
        except Exception as e:
            print(f"⚠️  Erreur Ollama: {e}")
            return self.default_metadata()
    
    def extract_batch(self, texts: List[str]) -> List[Dict]:
        """Extraction parallèle de plusieurs textes"""
        return asyncio.run(self._extract_batch_async(texts))
    
    async def _extract_batch_async(self, texts: List[str]) -> List[Dict]:
        """Extraction asynchrone en parallèle avec limite de concurrence"""
        semaphore = asyncio.Semaphore(self.max_concurrent)
        
        async def extract_with_limit(text: str) -> Dict:
            async with semaphore:
                return await self._extract_async(text)
        
        tasks = [extract_with_limit(text) for text in texts]
        results = await asyncio.gather(*tasks)
        return list(results)
    
    def _build_prompt(self, text: str) -> str:
        return f"""Tu es un analyseur de métadonnées. Analyse ce texte et retourne UNIQUEMENT un JSON valide.

TEXTE: "{text}"

EXEMPLES:
- "Je suis excité!" → tags_roget: ["06-0020-0100"], valence: 0.8
- "Ça m'énerve..." → tags_roget: ["06-0020-0140"], valence: -0.6

FORMAT JSON:
{{"tags_roget": ["XX-XXXX-XXXX"], "emotion_valence": 0.0, "emotion_activation": 0.5, "cognition_certitude": 0.5, "cognition_complexite": 0.5, "cognition_abstraction": 0.5, "physique_energie": null, "physique_stress": null, "comm_clarte": 0.7, "comm_formalite": 0.3, "entites": {{"personnes": [], "lieux": [], "projets": [], "organisations": []}}, "type_contenu": "reflexion", "resume_texte": "", "resume_mots_cles": []}}

JSON:"""

    def _parse_response(self, response_text: str) -> Dict:
        start = response_text.find('{')
        end = response_text.rfind('}') + 1
        if start != -1 and end > start:
            json_str = self._clean_json(response_text[start:end])
            try:
                return json.loads(json_str)
            except:
                pass
        return self.default_metadata()
    
    def _clean_json(self, json_str: str) -> str:
        json_str = re.sub(r'//.*?$', '', json_str, flags=re.MULTILINE)
        json_str = re.sub(r'\bTrue\b', 'true', json_str)
        json_str = re.sub(r'\bFalse\b', 'false', json_str)
        json_str = re.sub(r'\bNone\b', 'null', json_str)
        json_str = re.sub(r',(\s*[\]\}])', r'\1', json_str)
        return json_str.strip()