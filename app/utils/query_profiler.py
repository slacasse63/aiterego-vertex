"""
query_profiler.py - Génération dynamique de QueryProfile via Gemini Flash

Le QueryProfile définit COMMENT Hermès doit scorer les segments pour une requête donnée.
Principe fondamental: "La pondération n'est pas une propriété du segment, mais de la requête."

Architecture:
    User Query → Gemini Flash (analyse intention) → QueryProfile JSON → Hermès (applique)

Usage:
    from utils.query_profiler import QueryProfiler
    
    profiler = QueryProfiler()
    profile = profiler.analyze("Qui travaillait sur MOSS l'an passé?")
    # → {"weights": {"personnes": 0.40, "timestamp": 0.30, ...}, "filters": {...}}

Session de référence: 22_session_query_profile_architecture.json
"""

import os
import json
import logging
from typing import Optional, Dict, Any
from pathlib import Path
from dataclasses import dataclass, asdict
from dotenv import load_dotenv

# Charger les variables d'environnement
env_path = Path(__file__).parent.parent.parent / ".env"
load_dotenv(env_path)

from google import genai

logger = logging.getLogger(__name__)


# === CONFIGURATION ===
from .gemini_provider import DEFAULT_MODEL
PROFILER_MODEL = DEFAULT_MODEL # Modèle Gemini pour le profiling


# === STRUCTURE DU QUERY PROFILE ===
@dataclass
class QueryProfile:
    """
    Profil de pondération pour une requête.
    Généré par Gemini Flash, consommé par Hermès.
    """
    # Pondérations inter-champs (doivent sommer à 1.0)
    weights: Dict[str, float]
    
    # Filtres SQL optionnels
    filters: Dict[str, Any]
    
    # Stratégie de recherche
    strategy: Dict[str, Any]
    
    # Métadonnées de génération
    intent: str  # "temporel", "personne", "thematique", "emotion", "mixte"
    confidence: float  # 0.0 à 1.0
    
    def to_dict(self) -> dict:
        return asdict(self)
    
    @classmethod
    def default(cls) -> "QueryProfile":
        """Profil par défaut (ancien comportement 40/40/20)."""
        return cls(
            weights={
                "tags_roget": 0.30,
                "emotion": 0.30,
                "timestamp": 0.30,
                "personnes": 0.0,
                "resume_texte": 0.10
            },
            filters={
                "date_range_days": None,
                "type_contenu": None,
                "domaine": None
            },
            strategy={
                "top_k": 5,
                "include_text_fallback": True
            },
            intent="mixte",
            confidence=0.5
        )


# === PROMPT SYSTÈME POUR L'ANALYSE D'INTENTION ===
SYSTEM_PROMPT = """Tu es un analyseur d'intention pour un système de mémoire sémantique.

Ta tâche: Analyser une requête utilisateur et déterminer COMMENT chercher dans la mémoire.

Tu dois retourner un JSON avec:
1. **weights**: Pondérations entre 0.0 et 1.0 pour chaque champ (DOIT sommer à 1.0)
   - timestamp: pour les requêtes temporelles ("quand", "hier", "l'an passé")
   - personnes: pour les requêtes sur des individus ("qui", "avec qui", noms propres)
   - tags_roget: pour les requêtes thématiques (sujets, concepts, domaines)
   - emotion: pour les requêtes sur des états émotionnels ("frustré", "content", "stressé")
   - resume_texte: pour les recherches textuelles générales

2. **filters**: Filtres à appliquer
   - date_range_days: nombre de jours à considérer (null = tout)
   - type_contenu: "question", "decision", "reflexion", ou null
   - domaine: "professionnel", "personnel", "technique", ou null

3. **strategy**: Paramètres de recherche
   - top_k: nombre de résultats (3-10)
   - include_text_fallback: true/false

4. **intent**: Type d'intention principale
   - "temporel": quand quelque chose s'est passé
   - "personne": qui était impliqué
   - "thematique": sur quel sujet
   - "emotion": quel était l'état émotionnel
   - "mixte": combinaison de plusieurs

5. **confidence**: Confiance dans l'analyse (0.0 à 1.0)

RÈGLES IMPORTANTES:
- Les weights DOIVENT sommer à 1.0
- Favorise UN champ dominant (0.4-0.6) avec des secondaires (0.1-0.3)
- Pour les requêtes vagues, utilise une distribution équilibrée
- date_range_days: 1 pour "hier", 7 pour "cette semaine", 30 pour "ce mois", 365 pour "cette année"

EXEMPLES:

Requête: "C'était quand déjà qu'on a parlé de Christian?"
→ {
  "weights": {"timestamp": 0.45, "personnes": 0.35, "tags_roget": 0.15, "emotion": 0.05, "resume_texte": 0.0},
  "filters": {"date_range_days": null, "type_contenu": null, "domaine": null},
  "strategy": {"top_k": 5, "include_text_fallback": true},
  "intent": "temporel",
  "confidence": 0.85
}

Requête: "Quand j'étais frustré par le code"
→ {
  "weights": {"emotion": 0.50, "tags_roget": 0.25, "timestamp": 0.15, "personnes": 0.05, "resume_texte": 0.05},
  "filters": {"date_range_days": null, "type_contenu": null, "domaine": "technique"},
  "strategy": {"top_k": 5, "include_text_fallback": true},
  "intent": "emotion",
  "confidence": 0.80
}

Requête: "Qu'est-ce qu'on a décidé pour le projet MOSS?"
→ {
  "weights": {"tags_roget": 0.45, "resume_texte": 0.25, "timestamp": 0.15, "personnes": 0.10, "emotion": 0.05},
  "filters": {"date_range_days": null, "type_contenu": "decision", "domaine": "professionnel"},
  "strategy": {"top_k": 8, "include_text_fallback": true},
  "intent": "thematique",
  "confidence": 0.90
}

Réponds UNIQUEMENT avec le JSON, sans commentaires ni markdown."""


class QueryProfiler:
    """
    Génère des QueryProfiles via Gemini Flash.
    
    Le QueryProfile voyage de Gemini à Hermès, JAMAIS au Scribe.
    """
    
    def __init__(self, model: str = PROFILER_MODEL):
        """
        Initialise le profiler.
        
        Args:
            model: Modèle Gemini à utiliser (Flash recommandé pour la vitesse)
        """
        self.api_key = os.getenv("GEMINI_API_KEY")
        if not self.api_key:
            raise ValueError("GEMINI_API_KEY non trouvée")
        
        self.model = model
        self.client = genai.Client(api_key=self.api_key)
        
        logger.info(f"QueryProfiler initialisé avec {model}")
    
    def analyze(self, query: str) -> QueryProfile:
        """
        Analyse une requête et génère un QueryProfile.
        
        Args:
            query: Requête utilisateur en langage naturel
            
        Returns:
            QueryProfile avec pondérations et filtres
        """
        try:
            response = self.client.models.generate_content(
                model=self.model,
                contents=f"Requête à analyser: {query}",
                config=genai.types.GenerateContentConfig(
                    system_instruction=SYSTEM_PROMPT,
                    temperature=0.1,
                    max_output_tokens=2048,
                    response_mime_type="application/json",
                    safety_settings=[
                        genai.types.SafetySetting(
                            category="HARM_CATEGORY_HARASSMENT",
                            threshold="BLOCK_NONE"
                        ),
                        genai.types.SafetySetting(
                            category="HARM_CATEGORY_HATE_SPEECH",
                            threshold="BLOCK_NONE"
                        ),
                        genai.types.SafetySetting(
                            category="HARM_CATEGORY_SEXUALLY_EXPLICIT",
                            threshold="BLOCK_NONE"
                        ),
                        genai.types.SafetySetting(
                            category="HARM_CATEGORY_DANGEROUS_CONTENT",
                            threshold="BLOCK_NONE"
                        ),
                    ]
                )
            )
            
            # Parser le JSON
            profile_data = self._parse_response(response.text)
            
            # Valider et normaliser
            profile = self._validate_profile(profile_data)
            
            logger.info(f"QueryProfile généré: intent={profile.intent}, confidence={profile.confidence}")
            
            return profile
            
        except Exception as e:
            logger.warning(f"Erreur QueryProfiler, fallback au défaut: {e}")
            return QueryProfile.default()
    
    def _parse_response(self, response_text: str) -> dict:
        """
        Parse la réponse JSON de Gemini en nettoyant les artefacts (Markdown, Thoughts).
        """
        import re
        
        # DEBUG COMPLET
        print(f"DEBUG PROFILER FULL RAW:\n{response_text}\n---END RAW---")

        if not response_text:
            raise ValueError("Réponse vide de Gemini")

        clean_text = response_text.strip()

        # Extraction chirurgicale du JSON via Regex
        json_match = re.search(r"(\{.*\})", clean_text, re.DOTALL)
        
        if json_match:
            clean_text = json_match.group(1)
            print(f"DEBUG PROFILER EXTRACTED JSON:\n{clean_text}\n---END EXTRACTED---")
        else:
            # Fallback : Nettoyage Markdown classique
            if "```" in clean_text:
                clean_text = clean_text.split("```")[1]
                if clean_text.startswith("json"):
                    clean_text = clean_text[4:]
            clean_text = clean_text.strip()

        return json.loads(clean_text)
    
    def _validate_profile(self, data: dict) -> QueryProfile:
        """Valide et normalise un profil."""
        # Extraire les weights avec défauts
        weights = data.get("weights", {})
        default_weights = {
            "tags_roget": 0.40,
            "emotion": 0.40,
            "timestamp": 0.20,
            "personnes": 0.0,
            "resume_texte": 0.0
        }
        
        # Compléter les weights manquants
        for key in default_weights:
            if key not in weights:
                weights[key] = default_weights[key]
        
        # Normaliser pour que la somme = 1.0
        total = sum(weights.values())
        if total > 0 and abs(total - 1.0) > 0.01:
            weights = {k: v / total for k, v in weights.items()}
        
        # Extraire les filtres avec défauts
        filters = data.get("filters", {})
        default_filters = {
            "date_range_days": None,
            "type_contenu": None,
            "domaine": None
        }
        for key in default_filters:
            if key not in filters:
                filters[key] = default_filters[key]
        
        # Extraire la stratégie avec défauts
        strategy = data.get("strategy", {})
        default_strategy = {
            "top_k": 5,
            "include_text_fallback": True
        }
        for key in default_strategy:
            if key not in strategy:
                strategy[key] = default_strategy[key]
        
        # Clamp top_k entre 3 et 10
        strategy["top_k"] = max(3, min(10, strategy["top_k"]))
        
        return QueryProfile(
            weights=weights,
            filters=filters,
            strategy=strategy,
            intent=data.get("intent", "mixte"),
            confidence=max(0.0, min(1.0, data.get("confidence", 0.5)))
        )
    
    def analyze_batch(self, queries: list) -> list:
        """
        Analyse plusieurs requêtes (pour tests ou benchmarks).
        
        Args:
            queries: Liste de requêtes
            
        Returns:
            Liste de QueryProfiles
        """
        return [self.analyze(q) for q in queries]


# === TEST ===
if __name__ == "__main__":
    import time
    
    print("=" * 60)
    print("QUERY PROFILER - Test")
    print("=" * 60)
    
    try:
        profiler = QueryProfiler()
        
        test_queries = [
            "C'était quand déjà qu'on a parlé de MOSS?",
            "Qui travaillait sur le projet l'an passé?",
            "Quand j'étais frustré par les bugs",
            "Qu'est-ce qu'on a décidé pour l'architecture?",
            "Parle-moi de mes conversations avec Christian",
        ]
        
        for query in test_queries:
            print(f"\n📝 Requête: {query}")
            
            start = time.time()
            profile = profiler.analyze(query)
            elapsed = (time.time() - start) * 1000
            
            print(f"   ⏱️  {elapsed:.0f}ms")
            print(f"   🎯 Intent: {profile.intent} (confiance: {profile.confidence:.0%})")
            print(f"   ⚖️  Weights: ", end="")
            
            # Afficher les weights triés par importance
            sorted_weights = sorted(profile.weights.items(), key=lambda x: x[1], reverse=True)
            for field, weight in sorted_weights:
                if weight > 0.05:
                    print(f"{field}={weight:.0%} ", end="")
            print()
            
            if profile.filters.get("date_range_days"):
                print(f"   📅 Filtre temporel: {profile.filters['date_range_days']} jours")
            if profile.filters.get("type_contenu"):
                print(f"   📋 Type: {profile.filters['type_contenu']}")
            if profile.filters.get("domaine"):
                print(f"   🏷️  Domaine: {profile.filters['domaine']}")
        
        print("\n" + "=" * 60)
        print("✅ Tests terminés!")
        
    except Exception as e:
        print(f"\n❌ Erreur: {e}")
        import traceback
        traceback.print_exc()