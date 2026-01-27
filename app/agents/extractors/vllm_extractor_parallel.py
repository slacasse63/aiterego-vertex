"""
Extracteur utilisant vLLM sur VALERIA via API compatible OpenAI.
Version 3.0 - PARALLÈLE avec asyncio
"""

import asyncio
import json
import re
import time
from typing import List, Dict, Optional
import httpx
from .base import BaseExtractor

# Configuration vLLM local
VLLM_BASE_URL = "http://localhost:8000/v1"
VLLM_MODEL = "mistralai/Mistral-Nemo-Instruct-2407"
DEFAULT_BATCH_SIZE = 20
MAX_RETRIES = 3
RETRY_DELAY = 5
TIMEOUT = 300.0

# === NOUVEAU: Parallélisme ===
PARALLEL_BATCHES = 3  # Nombre de batches envoyés simultanément

class VLLMExtractor(BaseExtractor):
    
    def __init__(self, base_url: str = VLLM_BASE_URL, model: str = VLLM_MODEL, 
                 batch_size: int = DEFAULT_BATCH_SIZE, parallel_batches: int = PARALLEL_BATCHES):
        self.base_url = base_url
        self.model = model
        self.batch_size = batch_size
        self.parallel_batches = parallel_batches
        # Client sync pour compatibilité
        self.client = httpx.Client(timeout=TIMEOUT)
    
    # === MÉTHODES SYNC (compatibilité) ===
    
    def extract(self, text: str) -> Dict:
        results = self.extract_batch([text])
        return results[0] if results else self.default_metadata()
    
    def extract_batch(self, texts: List[str]) -> List[Dict]:
        """Méthode sync originale - pour compatibilité."""
        if not texts:
            return []
        
        texts = [t[:2000] if len(t) > 2000 else t for t in texts]
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
                        "max_tokens": 8000
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
                    return [self.default_metadata() for _ in texts]
        
        return [self.default_metadata() for _ in texts]
    
    # === MÉTHODES ASYNC (NOUVEAU) ===
    
    async def _extract_batch_async(self, texts: List[str], batch_id: int, 
                                    client: httpx.AsyncClient) -> tuple[int, List[Dict]]:
        """Traite UN batch de manière asynchrone."""
        if not texts:
            return batch_id, []
        
        texts = [t[:2000] if len(t) > 2000 else t for t in texts]
        prompt = self._build_batch_prompt(texts)
        
        for attempt in range(MAX_RETRIES):
            try:
                response = await client.post(
                    f"{self.base_url}/chat/completions",
                    json={
                        "model": self.model,
                        "messages": [
                            {"role": "system", "content": "Tu es un analyseur de métadonnées expert. Tu retournes UNIQUEMENT du JSON valide, sans texte avant ou après."},
                            {"role": "user", "content": prompt}
                        ],
                        "temperature": 0.1,
                        "max_tokens": 8000
                    }
                )
                response.raise_for_status()
                data = response.json()
                content = data["choices"][0]["message"]["content"]
                results = self._parse_batch_response(content, len(texts))
                return batch_id, results
                    
            except Exception as e:
                print(f"      ⚠️  Batch {batch_id} erreur (tentative {attempt+1}): {e}")
                if attempt < MAX_RETRIES - 1:
                    await asyncio.sleep(RETRY_DELAY)
                    continue
                else:
                    return batch_id, [self.default_metadata() for _ in texts]
        
        return batch_id, [self.default_metadata() for _ in texts]
    
    async def extract_all_parallel(self, all_texts: List[str], 
                                    progress_callback=None) -> List[Dict]:
        """
        Traite TOUS les segments en parallèle par groupes de batches.
        
        Args:
            all_texts: Liste de tous les textes à traiter
            progress_callback: Fonction optionnelle appelée après chaque groupe
                              callback(segments_done, total_segments, elapsed_seconds)
        
        Returns:
            Liste de métadonnées dans l'ordre original
        """
        if not all_texts:
            return []
        
        # Découper en batches
        batches = []
        for i in range(0, len(all_texts), self.batch_size):
            batches.append(all_texts[i:i + self.batch_size])
        
        total_batches = len(batches)
        total_segments = len(all_texts)
        all_results = [None] * total_batches  # Placeholder pour garder l'ordre
        
        print(f"\n  📦 {total_segments} segments → {total_batches} batches (taille {self.batch_size})")
        print(f"  ⚡ Parallélisme: {self.parallel_batches} batches simultanés")
        
        start_time = time.time()
        processed_batches = 0
        
        async with httpx.AsyncClient(timeout=TIMEOUT) as client:
            # Traiter par groupes de parallel_batches
            for group_start in range(0, total_batches, self.parallel_batches):
                group_end = min(group_start + self.parallel_batches, total_batches)
                group_indices = range(group_start, group_end)
                
                # Lancer les batches du groupe en parallèle
                tasks = [
                    self._extract_batch_async(batches[i], i, client)
                    for i in group_indices
                ]
                
                results = await asyncio.gather(*tasks)
                
                # Stocker les résultats dans l'ordre
                for batch_id, batch_results in results:
                    all_results[batch_id] = batch_results
                    processed_batches += 1
                
                # Progress callback
                elapsed = time.time() - start_time
                segments_done = min((group_end) * self.batch_size, total_segments)
                
                if progress_callback:
                    progress_callback(segments_done, total_segments, elapsed)
                else:
                    # Affichage par défaut
                    pct = (segments_done / total_segments) * 100
                    rate = segments_done / elapsed if elapsed > 0 else 0
                    eta = (total_segments - segments_done) / rate if rate > 0 else 0
                    
                    elapsed_str = f"{int(elapsed//60):02d}:{int(elapsed%60):02d}"
                    eta_str = f"{int(eta//60):02d}:{int(eta%60):02d}"
                    
                    print(f"  ✓ Batches {group_start+1}-{group_end}/{total_batches} "
                          f"({pct:.0f}%) - {elapsed_str} écoulé - ETA {eta_str}")
        
        # Aplatir les résultats
        final_results = []
        for batch_results in all_results:
            if batch_results:
                final_results.extend(batch_results)
        
        # Rapport final
        total_time = time.time() - start_time
        rate = total_segments / total_time if total_time > 0 else 0
        print(f"\n  ✅ Terminé: {total_segments} segments en {total_time:.1f}s ({rate:.2f} seg/s)")
        
        return final_results
    
    def extract_all_parallel_sync(self, all_texts: List[str], 
                                   progress_callback=None) -> List[Dict]:
        """
        Wrapper synchrone pour extract_all_parallel.
        Utiliser cette méthode depuis du code non-async.
        """
        return asyncio.run(self.extract_all_parallel(all_texts, progress_callback))

    # === MÉTHODES UTILITAIRES (inchangées) ===
    
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

INDICES ÉMOTIONNELS À DÉTECTER:
- Ponctuation: !!! = activation haute, ... = hésitation/fatigue
- Mots positifs: "excité", "content", "super", "génial", "eureka"
- Mots négatifs: "frustré", "épuisé", "problème", "erreur", "stress"

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
        # Retirer les backticks markdown
        content = re.sub(r'```json\s*', '', content)
        content = re.sub(r'```\s*', '', content)
        
        # Trouver le JSON array
        start = content.find('[')
        end = content.rfind(']') + 1
        
        if start == -1 or end <= start:
            print(f"      ⚠️  Pas de JSON array trouvé")
            return [self.default_metadata() for _ in range(expected)]
        
        json_str = content[start:end]
        json_str = self._clean_json(json_str)
        
        try:
            results = json.loads(json_str)
            while len(results) < expected:
                results.append(self.default_metadata())
            return [self._validate_metadata(r) for r in results]
        except json.JSONDecodeError as e:
            print(f"      ⚠️  Erreur JSON: {e}")
            return [self.default_metadata() for _ in range(expected)]
    
    def _clean_json(self, json_str: str) -> str:
        """Nettoie le JSON mal formé."""
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
        json_str = re.sub(r'(")\s*\n(\s*")', r'\1,\n\2', json_str)
        json_str = re.sub(r'(\d|true|false|null)\s*\n(\s*")', r'\1,\n\2', json_str)
        json_str = re.sub(r'([\]\}])\s*\n(\s*")', r'\1,\n\2', json_str)
        
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