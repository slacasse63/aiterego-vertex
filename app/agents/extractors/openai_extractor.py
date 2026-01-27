"""
Extracteur utilisant OpenAI GPT-4o-mini en mode BATCH.
Version 2.2 - Avec nettoyage JSON robuste

~50 segments par appel = ~50x plus rapide que Ollama
"""

import json
import os
import re
import time
from typing import List, Dict
from openai import OpenAI
from .base import BaseExtractor

DEFAULT_MODEL = "gpt-4o-mini"
DEFAULT_BATCH_SIZE = 20
MAX_RETRIES = 3
RETRY_DELAY = 25

class OpenAIExtractor(BaseExtractor):
    
    def __init__(self, api_key: str = None, model: str = DEFAULT_MODEL, batch_size: int = DEFAULT_BATCH_SIZE):
        self.api_key = api_key or os.getenv("OPENAI_API_KEY")
        if not self.api_key:
            raise ValueError("Clé API OpenAI requise")
        self.client = OpenAI(api_key=self.api_key)
        self.model = model
        self.batch_size = batch_size
    
    def extract(self, text: str) -> Dict:
        results = self.extract_batch([text])
        return results[0] if results else self.default_metadata()
    
    def extract_batch(self, texts: List[str]) -> List[Dict]:
        if not texts:
            return []
        
        texts = [t[:2000] if len(t) > 2000 else t for t in texts]
        prompt = self._build_batch_prompt(texts)
        
        for attempt in range(MAX_RETRIES):
            try:
                response = self.client.chat.completions.create(
                    model=self.model,
                    messages=[
                        {"role": "system", "content": "Tu extrais des métadonnées. Retourne UNIQUEMENT un JSON array valide."},
                        {"role": "user", "content": prompt}
                    ],
                    temperature=0.1,
                    max_tokens=8000
                )
                content = response.choices[0].message.content
                results = self._parse_batch_response(content, len(texts))
                return results
                    
            except Exception as e:
                error_str = str(e)
                if "429" in error_str or "rate_limit" in error_str.lower():
                    wait_time = RETRY_DELAY * (attempt + 1)
                    print(f"      ⏳ Rate limit, attente {wait_time}s... (retry {attempt + 1}/{MAX_RETRIES})")
                    time.sleep(wait_time)
                    continue
                else:
                    print(f"      ⚠️  Erreur OpenAI: {e}")
                    if attempt < MAX_RETRIES - 1:
                        time.sleep(RETRY_DELAY)
                        continue
                    else:
                        return [self.default_metadata() for _ in texts]
        
        return [self.default_metadata() for _ in texts]
    
    def _clean_json(self, json_str: str) -> str:
        """
        Nettoie le JSON mal formé retourné par OpenAI.
        Même logique que pour Ollama.
        """
        # Supprimer les commentaires
        json_str = re.sub(r'//.*?$', '', json_str, flags=re.MULTILINE)
        json_str = re.sub(r'/\*.*?\*/', '', json_str, flags=re.DOTALL)
        
        # Guillemets simples → doubles
        json_str = re.sub(r"'(\w+)'(\s*:)", r'"\1"\2', json_str)
        json_str = re.sub(r":\s*'([^']*)'", r': "\1"', json_str)
        
        # Booléens/null Python → JSON
        json_str = re.sub(r'\bTrue\b', 'true', json_str)
        json_str = re.sub(r'\bFalse\b', 'false', json_str)
        json_str = re.sub(r'\bNone\b', 'null', json_str)
        json_str = re.sub(r'\bNULL\b', 'null', json_str)
        json_str = re.sub(r'\bNull\b', 'null', json_str)
        
        # Clés sans guillemets
        json_str = re.sub(
            r'([{\,])\s*([a-zA-Z_][a-zA-Z0-9_]*)\s*:',
            r'\1 "\2":',
            json_str
        )
        
        # Virgules trailing avant ] ou }
        json_str = re.sub(r',(\s*[\]\}])', r'\1', json_str)
        
        # === VIRGULES MANQUANTES ===
        # Entre "valeur" et "clé":
        json_str = re.sub(r'(")\s*\n(\s*")', r'\1,\n\2', json_str)
        # Entre nombre/bool/null et "clé":
        json_str = re.sub(r'(\d|true|false|null)\s*\n(\s*")', r'\1,\n\2', json_str)
        # Entre ] ou } et "clé":
        json_str = re.sub(r'([\]\}])\s*\n(\s*")', r'\1,\n\2', json_str)
        
        # Virgules manquantes sur même ligne (cas rare)
        json_str = re.sub(r'"\s+"', '", "', json_str)
        json_str = re.sub(r'(\d)\s+"', r'\1, "', json_str)
        json_str = re.sub(r'(true|false|null)\s+"', r'\1, "', json_str)
        json_str = re.sub(r'\}\s*\{', '}, {', json_str)
        json_str = re.sub(r'\]\s*\{', '], {', json_str)
        
        # Caractères de contrôle
        json_str = re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f]', '', json_str)
        
        # Re-nettoyer virgules trailing
        json_str = re.sub(r',(\s*[\]\}])', r'\1', json_str)
        
        return json_str.strip()
    
    def _build_batch_prompt(self, texts: List[str]) -> str:
        segments = json.dumps([{"id": i, "text": t} for i, t in enumerate(texts)], ensure_ascii=False)
        return f"""Analyse ces {len(texts)} segments. Retourne un JSON array.

SEGMENTS:
{segments}

FORMAT pour chaque segment:
{{"id": 0, "tags_roget": ["XX-XXXX-XXXX"], "emotion_valence": 0.0, "emotion_activation": 0.5, "cognition_certitude": 0.5, "cognition_complexite": 0.5, "cognition_abstraction": 0.5, "physique_energie": null, "physique_stress": null, "comm_clarte": 0.7, "comm_formalite": 0.3, "entites": {{"personnes": [], "lieux": [], "projets": [], "organisations": []}}, "type_contenu": "reflexion", "resume_texte": "", "resume_mots_cles": []}}

TAGS ROGET:
- 04-0120-0070 = Question
- 06-0020-0100 = Joie
- 06-0020-0140 = Frustration
- 06-0020-0110 = Fatigue
- 06-0030-0110 = Amour/Famille

RETOURNE UNIQUEMENT LE JSON ARRAY:"""

    def _parse_batch_response(self, content: str, expected: int) -> List[Dict]:
        # Retirer les backticks markdown (```json ... ```)
        content = re.sub(r'```json\s*', '', content)
        content = re.sub(r'```\s*', '', content)
        
        # Trouver le JSON array
        start = content.find('[')
        end = content.rfind(']') + 1
        
        if start == -1 or end <= start:
            print(f"      ⚠️  Pas de JSON array trouvé")
            return [self.default_metadata() for _ in range(expected)]
        
        json_str = content[start:end]
        
        # Nettoyer le JSON
        json_str = self._clean_json(json_str)
        
        try:
            results = json.loads(json_str)
            while len(results) < expected:
                results.append(self.default_metadata())
            return [self._validate_metadata(r) for r in results]
        except json.JSONDecodeError as e:
            print(f"      ⚠️  Erreur JSON: {e}")
            return [self.default_metadata() for _ in range(expected)]
    
    def _validate_metadata(self, metadata: Dict) -> Dict:
        if "tags_roget" not in metadata or not metadata["tags_roget"]:
            metadata["tags_roget"] = ["04-0110-0010"]
        
        for field, default in [
            ("emotion_valence", 0.0),
            ("emotion_activation", 0.5),
            ("cognition_certitude", 0.5),
            ("cognition_complexite", 0.5),
            ("cognition_abstraction", 0.5),
            ("comm_clarte", 0.5),
            ("comm_formalite", 0.5)
        ]:
            val = metadata.get(field)
            if val is None or not isinstance(val, (int, float)):
                try:
                    metadata[field] = float(val) if val else default
                except:
                    metadata[field] = default
        
        for field in ["physique_energie", "physique_stress"]:
            val = metadata.get(field)
            if val is not None and not isinstance(val, (int, float)):
                try:
                    metadata[field] = float(val)
                except:
                    metadata[field] = None
        
        if "entites" not in metadata:
            metadata["entites"] = {"personnes": [], "lieux": [], "projets": [], "organisations": []}
        
        if "type_contenu" not in metadata:
            metadata["type_contenu"] = "information"
        if "" not in metadata:
            metadata[""] = "personnel"
        if "resume_texte" not in metadata:
            metadata["resume_texte"] = ""
        if "resume_mots_cles" not in metadata:
            metadata["resume_mots_cles"] = []
        
        return metadata