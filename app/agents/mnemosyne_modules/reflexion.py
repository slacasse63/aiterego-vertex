"""
reflexion.py - Module de Réflexion pour Mnémosyne
MOSS v0.11.0 - Session 72

Action 2: Détection et tissage des trajectoires de pensée.

Responsabilités:
    - Détecter les évolutions de pensée (pas des erreurs)
    - Utiliser Word2Vec pour trouver les clusters évolutifs
    - Créer les liens TRAJECTOIRE, GENEALOGIE, EVOLUE_VERS
    - Proposer de nouveaux piliers

Distinction importante:
    - RECTIFICATION = corriger une ERREUR factuelle
    - RÉFLEXION = tisser les ÉVOLUTIONS de pensée (A → B → C)

Workflow:
    1. Analyse Gemini du contenu pour détecter les évolutions
    2. Word2Vec pour trouver les concepts liés dans le passé
    3. Création des liens de trajectoire
    4. Proposition de piliers consolidés

Usage:
    Appelé par mnemosyne.py en mode 'reflexion' ou 'complet'.
"""

import re
import json
from typing import List, Dict, Optional, Any
from dataclasses import dataclass, field

from google import genai
from google.genai import types

from .sbire import Sbire, Mandat


@dataclass
class Trajectoire:
    """Une évolution de pensée détectée."""
    ancien_concept: str = ""
    nouveau_concept: str = ""
    type_evolution: str = "TRAJECTOIRE"  # TRAJECTOIRE, GENEALOGIE, EVOLUE_VERS
    description: str = ""
    confidence: float = 0.0
    source_ids: List[int] = field(default_factory=list)
    target_id: Optional[int] = None


@dataclass
class PilierPropose:
    """Un pilier proposé pour consolidation."""
    fait: str = ""
    categorie: str = "FAIT"
    importance: int = 2
    raison: str = ""
    source_ids: List[int] = field(default_factory=list)


@dataclass
class ReflexionResult:
    """Résultat du module Réflexion."""
    trajectoires_detectees: int = 0
    liens_crees: int = 0
    piliers_proposes: int = 0
    trajectoires: List[Trajectoire] = field(default_factory=list)
    piliers: List[PilierPropose] = field(default_factory=list)
    erreurs: List[str] = field(default_factory=list)


class Reflexion:
    """
    Module de Réflexion - Tissage des trajectoires de pensée.
    
    Détecte les évolutions conceptuelles et crée les liens
    qui forment la "mémoire généalogique" du système.
    """
    
    def __init__(self, config, sbire: Sbire, api_key: str):
        """
        Initialise le module Réflexion.
        
        Args:
            config: MnemosyneConfig
            sbire: Instance du Sbire
            api_key: Clé API Gemini
        """
        self.config = config
        self.sbire = sbire
        self.client = genai.Client(api_key=api_key)
        self.result = ReflexionResult()
    
    def process(self, content: str) -> Dict[str, Any]:
        """
        Traite le contenu pour détecter les trajectoires.
        
        Args:
            content: Contenu du fichier tokenisé
            
        Returns:
            Dictionnaire avec les résultats
        """
        # Phase 1: Détecter les évolutions
        print(f"   🔍 Détection des trajectoires...")
        trajectoires = self._detect_trajectoires(content)
        self.result.trajectoires_detectees = len(trajectoires)
        self.result.trajectoires = trajectoires
        
        print(f"      → {len(trajectoires)} trajectoire(s) détectée(s)")
        
        # Phase 2: Chercher les concepts liés dans le passé
        if trajectoires:
            print(f"   🔗 Tissage des liens...")
            self._weave_trajectories(trajectoires)
        
        # Phase 3: Proposer des piliers
        print(f"   📌 Analyse pour piliers...")
        piliers = self._propose_piliers(content, trajectoires)
        self.result.piliers_proposes = len(piliers)
        self.result.piliers = piliers
        
        print(f"      → {len(piliers)} pilier(s) proposé(s)")
        
        return self._to_dict()
    
    def _detect_trajectoires(self, content: str) -> List[Trajectoire]:
        """
        Détecte les évolutions de pensée dans le texte.
        
        Une évolution ≠ une erreur:
        - "On utilisait SQL, maintenant on passe à Vector" → TRAJECTOIRE
        - "Le projet a évolué de A vers B" → GENEALOGIE
        """
        
        if len(content) < 500:
            return []
        
        system_prompt = """Tu es Mnémosyne, l'agent de cohérence mémorielle de MOSS.

MISSION: Détecter les ÉVOLUTIONS DE PENSÉE (pas les erreurs).

Une évolution = changement d'approche, de technologie, de décision:
- "On utilisait X, maintenant on fait Y" → TRAJECTOIRE
- "Le projet a évolué de A vers B" → GENEALOGIE  
- "Avant on pensait X, maintenant on sait que Y" → EVOLUE_VERS

⚠️ IMPORTANT:
- Évolution ≠ Erreur
- Une évolution est un changement VALIDE de perspective
- On ne "corrige" pas, on "évolue"

Types de liens:
- TRAJECTOIRE: Changement de direction technique/conceptuel
- GENEALOGIE: Filiation entre concepts (B descend de A)
- EVOLUE_VERS: Maturation d'une idée

Réponds UNIQUEMENT en JSON valide:
{
  "trajectoires": [
    {
      "ancien_concept": "ce qu'on faisait/pensait avant",
      "nouveau_concept": "ce qu'on fait/pense maintenant",
      "type": "TRAJECTOIRE|GENEALOGIE|EVOLUE_VERS",
      "description": "résumé de l'évolution",
      "confidence": 0.0-1.0
    }
  ]
}

Si AUCUNE évolution: {"trajectoires": []}"""

        try:
            response = self.client.models.generate_content(
                model=self.config.model,
                contents=f"Analyse ce texte:\n\n{content[:6000]}",
                config=types.GenerateContentConfig(
                    system_instruction=system_prompt,
                    temperature=0.0,
                    max_output_tokens=2048
                )
            )
            
            text = self._extract_text(response)
            return self._parse_trajectoires_json(text)
            
        except Exception as e:
            if self.config.verbose:
                print(f"      ⚠️ Erreur Gemini trajectoires: {e}")
            self.result.erreurs.append(f"Gemini trajectoires: {e}")
            return []
    
    def _weave_trajectories(self, trajectoires: List[Trajectoire]):
        """
        Pour chaque trajectoire, cherche les concepts liés dans le passé
        et crée les liens appropriés.
        """
        for i, traj in enumerate(trajectoires, 1):
            if self.config.verbose:
                print(f"\n      [{i}/{len(trajectoires)}] {traj.type_evolution}: "
                      f"'{traj.ancien_concept[:30]}' → '{traj.nouveau_concept[:30]}'")
            
            # Chercher l'ancien concept dans la mémoire
            ancien_results = self._search_concept(traj.ancien_concept)
            nouveau_results = self._search_concept(traj.nouveau_concept)
            
            if ancien_results and nouveau_results:
                # On a trouvé les deux extrémités → créer le lien
                source_id = ancien_results[0].get('id')
                target_id = nouveau_results[0].get('id')
                
                if source_id and target_id and source_id != target_id:
                    traj.source_ids = [source_id]
                    traj.target_id = target_id
                    
                    if self.config.dry_run:
                        print(f"         🔍 [DRY-RUN] Créerait lien {source_id} → {target_id}")
                    else:
                        if self.sbire.insert_edge(
                            source_id,
                            target_id,
                            traj.type_evolution,
                            {
                                "description": traj.description[:200],
                                "confidence": traj.confidence,
                                "source": "mnemosyne_reflexion"
                            }
                        ):
                            self.result.liens_crees += 1
                            if self.config.verbose:
                                print(f"         ✅ Lien créé: {source_id} → {target_id}")
            else:
                if self.config.verbose:
                    print(f"         ⚠️ Concepts non trouvés dans la mémoire")
    
    def _search_concept(self, concept: str) -> List[Dict]:
        """Cherche un concept dans la mémoire via le Sbire."""
        
        # D'abord essayer Word2Vec (expansion sémantique)
        mandat = Mandat(
            type='word2vec',
            query=concept,
            max_results=10
        )
        
        results = self.sbire.execute(mandat)
        
        # Si pas de résultats, fallback SQL
        if not results:
            mandat = Mandat(
                type='sql',
                query=concept.split()[0] if concept.split() else concept,
                max_results=10
            )
            results = self.sbire.execute(mandat)
        
        return results
    
    def _propose_piliers(self, content: str, 
                         trajectoires: List[Trajectoire]) -> List[PilierPropose]:
        """
        Analyse le contenu pour proposer des piliers à consolider.
        
        Un pilier = un fait stable, important, qui mérite d'être
        cristallisé dans la mémoire.
        """
        
        if len(content) < 1000:
            return []
        
        # Préparer le contexte avec les trajectoires détectées
        traj_context = ""
        if trajectoires:
            traj_context = "\n\nTrajectoires détectées:\n" + "\n".join([
                f"- {t.ancien_concept} → {t.nouveau_concept}"
                for t in trajectoires[:5]
            ])
        
        system_prompt = """Tu es Mnémosyne, l'agent de cohérence mémorielle de MOSS.

MISSION: Identifier les FAITS IMPORTANTS qui méritent d'être des PILIERS.

Un pilier = vérité stable, importante, à retenir absolument:
- Décisions définitives ("On abandonne Valéria")
- Faits biographiques ("Serge est professeur à Laval")
- Choix techniques consolidés ("MOSS utilise Gemini, pas GPT")
- Dates importantes ("Prototype créé le 9 mai 2025")

Catégories:
- IDENTITE: Faits sur l'utilisateur
- RECHERCHE: Décisions de recherche
- TECHNIQUE: Choix techniques
- RELATION: Personnes, collaborateurs
- VALEUR: Principes, valeurs

Réponds UNIQUEMENT en JSON valide:
{
  "piliers": [
    {
      "fait": "énoncé clair du fait",
      "categorie": "IDENTITE|RECHERCHE|TECHNIQUE|RELATION|VALEUR",
      "importance": 1-3,
      "raison": "pourquoi c'est important"
    }
  ]
}

Si AUCUN pilier à proposer: {"piliers": []}"""

        try:
            response = self.client.models.generate_content(
                model=self.config.model,
                contents=f"Analyse ce texte:{traj_context}\n\n{content[:5000]}",
                config=types.GenerateContentConfig(
                    system_instruction=system_prompt,
                    temperature=0.0,
                    max_output_tokens=2048
                )
            )
            
            text = self._extract_text(response)
            piliers = self._parse_piliers_json(text)
            
            # Créer les piliers si pas en dry-run
            if not self.config.dry_run:
                for p in piliers:
                    pilier_id = self.sbire.insert_pilier(
                        fait=p.fait,
                        categorie=p.categorie,
                        importance=p.importance
                    )
                    if pilier_id and self.config.verbose:
                        print(f"      ✅ Pilier créé (ID {pilier_id}): {p.fait[:50]}...")
            else:
                for p in piliers:
                    print(f"      🔍 [DRY-RUN] Créerait pilier: {p.fait[:50]}...")
            
            return piliers
            
        except Exception as e:
            if self.config.verbose:
                print(f"      ⚠️ Erreur Gemini piliers: {e}")
            return []
    
    def _extract_text(self, response) -> str:
        """Extrait le texte d'une réponse Gemini."""
        try:
            if hasattr(response, 'text'):
                return response.text
            elif hasattr(response, 'candidates') and response.candidates:
                return response.candidates[0].content.parts[0].text
            else:
                return str(response)
        except:
            return ""
    
    def _parse_trajectoires_json(self, text: str) -> List[Trajectoire]:
        """Parse le JSON de trajectoires."""
        try:
            clean = text.strip()
            if clean.startswith("```"):
                clean = clean.split("```")[1]
                if clean.startswith("json"):
                    clean = clean[4:]
                clean = clean.strip()
            
            data = json.loads(clean)
            
            trajectoires = []
            for t in data.get("trajectoires", []):
                if t.get("ancien_concept") and t.get("nouveau_concept"):
                    trajectoires.append(Trajectoire(
                        ancien_concept=t.get("ancien_concept", ""),
                        nouveau_concept=t.get("nouveau_concept", ""),
                        type_evolution=t.get("type", "TRAJECTOIRE"),
                        description=t.get("description", ""),
                        confidence=t.get("confidence", 0.5)
                    ))
            
            return trajectoires
            
        except json.JSONDecodeError:
            return []
    
    def _parse_piliers_json(self, text: str) -> List[PilierPropose]:
        """Parse le JSON de piliers."""
        try:
            clean = text.strip()
            if clean.startswith("```"):
                clean = clean.split("```")[1]
                if clean.startswith("json"):
                    clean = clean[4:]
                clean = clean.strip()
            
            data = json.loads(clean)
            
            piliers = []
            for p in data.get("piliers", []):
                if p.get("fait"):
                    piliers.append(PilierPropose(
                        fait=p.get("fait", ""),
                        categorie=p.get("categorie", "FAIT"),
                        importance=min(3, max(1, p.get("importance", 2))),
                        raison=p.get("raison", "")
                    ))
            
            return piliers
            
        except json.JSONDecodeError:
            return []
    
    def _to_dict(self) -> Dict[str, Any]:
        """Convertit le résultat en dictionnaire."""
        return {
            "trajectoires_detectees": self.result.trajectoires_detectees,
            "liens_crees": self.result.liens_crees,
            "piliers_proposes": self.result.piliers_proposes,
            "erreurs": self.result.erreurs,
            "trajectoires": [
                {
                    "ancien": t.ancien_concept,
                    "nouveau": t.nouveau_concept,
                    "type": t.type_evolution,
                    "description": t.description
                }
                for t in self.result.trajectoires
            ],
            "piliers": [
                {
                    "fait": p.fait,
                    "categorie": p.categorie,
                    "importance": p.importance
                }
                for p in self.result.piliers
            ]
        }
