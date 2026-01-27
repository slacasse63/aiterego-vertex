"""
Extracteur utilisant vLLM sur VALERIA via API compatible OpenAI.
Version 2.4 - max_tokens=20000 + aggressive_fix + fallback + debug log
"""

import json
import re
import time
from typing import List, Dict, Optional
import httpx
from .base import BaseExtractor
from ftfy import fix_text

try:
    from json_repair import repair_json
    HAS_JSON_REPAIR = True
except ImportError:
    HAS_JSON_REPAIR = False

# Configuration vLLM local
VLLM_BASE_URL = "http://localhost:8000/v1"
VLLM_MODEL = "mistralai/Mistral-Nemo-Instruct-2407"
DEFAULT_BATCH_SIZE = 20
MAX_RETRIES = 3
RETRY_DELAY = 5
TIMEOUT = 300.0
MAX_TOKENS = 20000

class VLLMExtractor(BaseExtractor):
    
    def __init__(self, base_url: str = VLLM_BASE_URL, model: str = VLLM_MODEL, batch_size: int = DEFAULT_BATCH_SIZE):
        self.base_url = base_url
        self.model = model
        self.batch_size = batch_size
        self.client = httpx.Client(timeout=TIMEOUT)
        self._last_successful_metadata: Optional[Dict] = None
        self._error_count = 0
    
    def extract(self, text: str) -> Dict:
        results = self.extract_batch([text])
        return results[0] if results else self._fallback_metadata()
    
    def extract_batch(self, texts: List[str]) -> List[Dict]:
        if not texts:
            return []
        
        texts = [fix_text(t)[:2000] for t in texts]
        prompt = self._build_batch_prompt(texts)
        
        for attempt in range(MAX_RETRIES):
            try:
                response = self.client.post(
                    f"{self.base_url}/chat/completions",
                    json={
                        "model": self.model,
                        "messages": [
                            {"role": "system", "content": "Tu es un analyseur de métadonnées expert. Tu retournes UNIQUEMENT du JSON valide, sans texte avant ou après."},
                            {"role": "user", "content": prompt}
                        ],
                        "temperature": 0.1,
                        "max_tokens": MAX_TOKENS
                    }
                )
                response.raise_for_status()
                data = response.json()
                content = data["choices"][0]["message"]["content"]
                results = self._parse_batch_response(content, len(texts))
                return results
                    
            except Exception as e:
                print(f"      ⚠️  Erreur vLLM: {e}")
                if attempt < MAX_RETRIES - 1:
                    time.sleep(RETRY_DELAY)
                    continue
                else:
                    return [self._fallback_metadata() for _ in texts]
        
        return [self._fallback_metadata() for _ in texts]
    
    def _fallback_metadata(self) -> Dict:
        """Retourne le dernier metadata réussi, ou default si aucun."""
        if self._last_successful_metadata:
            fallback = self._last_successful_metadata.copy()
            fallback["resume_texte"] = "[Extraction échouée - contexte précédent]"
            return fallback
        return self.default_metadata()
    
    def _build_batch_prompt(self, texts: List[str]) -> str:
        """Prompt few-shot complet pour extraction de métadonnées."""
        segments = json.dumps([{"id": i, "text": t} for i, t in enumerate(texts)], ensure_ascii=False)
        
        return f"""Analyse ces {len(texts)} segments et retourne un JSON array.

SEGMENTS À ANALYSER:
{segments}

EXEMPLES D'ANALYSE (pour comprendre le format attendu):

Exemple 1 - Texte: "Je suis vraiment excité, on lance le projet demain!"
→ {{"id": 0, "tags_roget": ["06-0020-0100"], "emotion_valence": 0.8, "emotion_activation": 0.8, "type_contenu": "emotion", "resume_texte": "Enthousiasme pour lancement projet"}}

Exemple 2 - Texte: "Le serveur plante encore. J'ai essayé 3 fois, ça m'énerve..."
→ {{"id": 0, "tags_roget": ["06-0020-0140"], "emotion_valence": -0.6, "emotion_activation": 0.7, "type_contenu": "reflexion", "resume_texte": "Frustration problème serveur"}}

Exemple 3 - Texte: "C'est quoi la différence entre SQLite et PostgreSQL?"
→ {{"id": 0, "tags_roget": ["04-0120-0070"], "emotion_valence": 0.1, "emotion_activation": 0.4, "type_contenu": "question", "resume_texte": "Question technique bases de données"}}

Exemple 4 - Texte: "Ma fille Marie a eu 18 ans hier, on a fait la fête en famille"
→ {{"id": 0, "tags_roget": ["06-0030-0110"], "emotion_valence": 0.9, "emotion_activation": 0.7, "type_contenu": "narration", "entites": {{"personnes": ["Marie"]}}, "resume_texte": "Anniversaire 18 ans fille"}}

Exemple 5 - Texte: "Je suis épuisé, j'ai dormi 4 heures. Le stress me ronge."
→ {{"id": 0, "tags_roget": ["06-0020-0110"], "emotion_valence": -0.5, "emotion_activation": 0.3, "physique_energie": 0.2, "physique_stress": 0.8, "resume_texte": "Fatigue et stress"}}

GUIDE DES TAGS ROGET (utilise le plus spécifique):
- 04-0120-0070 = Question/Inquiry
- 04-0150-0130 = Knowledge/Information  
- 05-0110-0010 = Volonté/Intention (projets, plans)
- 05-0120-0060 = Business/Travail
- 06-0020-0010 = Plaisir
- 06-0020-0100 = Cheerfulness/Joie
- 06-0020-0110 = Dejection/Fatigue
- 06-0020-0140 = Aggravation/Frustration
- 06-0020-0330 = Hope/Espoir
- 06-0020-0350 = Fear/Peur
- 06-0030-0110 = Love/Amour (famille, affection)

FORMAT JSON POUR CHAQUE SEGMENT:
{{
  "id": 0,
  "tags_roget": ["XX-XXXX-XXXX"],
  "emotion_valence": 0.0,
  "emotion_activation": 0.5,
  "cognition_certitude": 0.5,
  "cognition_complexite": 0.5,
  "cognition_abstraction": 0.5,
  "physique_energie": null,
  "physique_stress": null,
  "comm_clarte": 0.7,
  "comm_formalite": 0.3,
  "entites": {{
    "personnes": [],
    "lieux": [],
    "projets": [],
    "organisations": []
  }},
  "type_contenu": "reflexion",
  "resume_texte": "Résumé court 5-10 mots",
  "resume_mots_cles": ["mot1", "mot2"]
}}

RÈGLES IMPORTANTES:
- emotion_valence: -1.0 (très négatif) à 1.0 (très positif)
- emotion_activation: 0.0 (calme) à 1.0 (intense)
- Extrais les noms propres dans entites
- type_contenu: question|decision|reflexion|information|tache|emotion|narration
-: personnel|professionnel|technique|creatif|administratif
- physique_energie et physique_stress: null sauf si explicitement mentionné

RETOURNE UNIQUEMENT UN JSON ARRAY VALIDE (pas de texte avant/après):
[
  {{"id": 0, ...}},
  {{"id": 1, ...}},
  ...
]"""

    def _parse_batch_response(self, content: str, expected: int) -> List[Dict]:
        """Parse la réponse JSON avec json_repair si disponible."""
        
        # Retirer les backticks markdown
        content = re.sub(r'```json\s*', '', content)
        content = re.sub(r'```\s*', '', content)
        
        # Trouver le JSON array
        start = content.find('[')
        if start == -1:
            print(f"      ⚠️  Pas de JSON array trouvé")
            return [self._fallback_metadata() for _ in range(expected)]
        
        json_str = content[start:]
        
        # === TENTATIVE 1: Parse direct ===
        try:
            results = json.loads(json_str)
            return self._process_results(results, expected)
        except json.JSONDecodeError as e:
            error_msg = str(e)
            print(f"      ⚠️  Erreur JSON: {error_msg}")
        
        # === TENTATIVE 2: json_repair ===
        if HAS_JSON_REPAIR:
            try:
                results = repair_json(json_str, return_objects=True)
                if not isinstance(results, list):
                    results = [results]
                print(f"      🛡️  JSON réparé automatiquement ({len(results)} objets)")
                return self._process_results(results, expected)
            except Exception as e2:
                print(f"      ⚠️  json_repair échoué: {e2}")
        
        # === TENTATIVE 3: Fallback ===
        self._error_count += 1
        debug_file = f"/tmp/json_error_{self._error_count}.txt"
        try:
            with open(debug_file, "w") as f:
                f.write(f"=== ERREUR ===\n{error_msg}\n\n")
                f.write(f"=== JSON ===\n{json_str}\n")
            print(f"      📝 Debug sauvegardé: {debug_file}")
        except:
            pass
        return [self._fallback_metadata() for _ in range(expected)]
    
    def _aggressive_fix(self, json_str: str, error: str) -> str:
        """Fix agressif : Nettoie les erreurs de syntaxe et AMPUTE les segments tronqués."""
        
        # 1. Nettoyage de base
        json_str = re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f]', '', json_str)
        json_str = re.sub(r'\bTrue\b', 'true', json_str)
        json_str = re.sub(r'\bFalse\b', 'false', json_str)
        json_str = re.sub(r'\bNone\b', 'null', json_str)
        
        # 2. STRATÉGIE AMPUTATION - Sauver les segments complets
        stripped = json_str.strip()
        if not stripped.endswith(']'):
            # Chercher le dernier objet complet avec regex
            # Pattern: }, suivi d'espaces/newlines et éventuellement { ou fin
            matches = list(re.finditer(r'\}\s*,', json_str))
            
            if matches:
                # Prendre la position après le dernier }, 
                last_match = matches[-1]
                last_complete_pos = last_match.start() + 1  # Position après le }
                
                # Couper et fermer le tableau
                json_str = json_str[:last_complete_pos] + ']'
                print(f"      🪚 Amputation: Segment(s) tronqué(s) retiré(s), reste du batch sauvé.")
            else:
                # Pas de }, trouvé - essayer de fermer brutalement
                pass
        
        # 3. Corrections syntaxiques
        if "Expecting ',' delimiter" in error:
            json_str = re.sub(r'"\s*\n\s*"', '",\n"', json_str)
            json_str = re.sub(r'\}\s*\{', '}, {', json_str)
            json_str = re.sub(r'"\s+"', '", "', json_str)
        
        # 4. Fermeture JSON tronqué (si amputation n'a pas suffi)
        if not json_str.rstrip().endswith(']'):
            open_braces = json_str.count('{') - json_str.count('}')
            open_brackets = json_str.count('[') - json_str.count(']')
            
            if json_str.count('"') % 2 == 0:  # Pas au milieu d'une string
                if open_braces > 0:
                    json_str = json_str.rstrip().rstrip(',')
                    json_str += '}' * open_braces
                if open_brackets > 0:
                    json_str += ']' * open_brackets
        
        # 5. Virgules trailing
        json_str = re.sub(r',\s*\}', '}', json_str)
        json_str = re.sub(r',\s*\]', ']', json_str)
        
        return json_str
    
    def _process_results(self, results: List[Dict], expected: int) -> List[Dict]:
        """Valide les résultats et met à jour le fallback."""
        while len(results) < expected:
            results.append(self._fallback_metadata())
        
        validated = []
        for r in results:
            v = self._validate_metadata(r)
            validated.append(v)
            self._last_successful_metadata = v.copy()
        
        return validated
    
    def _validate_metadata(self, metadata: Dict) -> Dict:
        """Valide et complète les métadonnées."""
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