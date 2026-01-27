"""
rectification.py - Module de Rectification pour Mnémosyne
MOSS v0.11.0 - Session 72

Action 1: Nettoyage et correction des erreurs factuelles.

Responsabilités:
    - Détecter les corrections explicites dans le texte
    - Chercher les erreurs passées correspondantes
    - Marquer les segments erronés (statut_verite = -1)
    - Créer les liens CORRIGE_PAR

Workflow:
    1. Patterns regex (gratuit, rapide)
    2. Gemini pour cas subtils (si nécessaire)
    3. Mandats au Sbire pour chercher les erreurs
    4. Analyse des résultats
    5. Actions: UPDATE statut_verite, INSERT edges

Usage:
    Appelé par mnemosyne.py en mode 'rectification' ou 'complet'.
    Conçu pour tourner en batch la nuit.
"""

import re
import json
from typing import List, Dict, Optional, Any
from dataclasses import dataclass, field

from google import genai
from google.genai import types

from .sbire import Sbire, Mandat


# Patterns de détection de corrections
CORRECTION_PATTERNS = [
    # Corrections explicites
    r"non[,\s]+c'est\s+(.+?)(?:\.|$)",
    r"en fait[,\s]+c'est\s+(.+?)(?:\.|$)",
    r"correction\s*:\s*(.+?)(?:\.|$)",
    
    # Rectifications de date/info
    r"la (?:vraie|bonne) (?:date|réponse|info)\s+(?:est|c'est)\s+(.+?)(?:\.|$)",
    r"(?:tu|vous)\s+(?:te|vous)\s+trompe[sz]?\s*[,:]?\s*(.+?)(?:\.|$)",
    
    # Négations correctrices
    r"c'est\s+(?:pas|plus)\s+(.+?)\s*[,;]\s*c'est\s+(.+?)(?:\.|$)",
    r"(?:ce n'est|c'est) pas\s+(.+?)\s*[,;]\s*(?:mais|c'est)\s+(.+?)(?:\.|$)",
    
    # Formes impératives
    r"oublie\s+(.+?)\s*[,;]\s*(?:c'est|utilise)\s+(.+?)(?:\.|$)",
    r"ne\s+(?:dis|utilise)\s+plus\s+(.+?)(?:\.|$)",
]


@dataclass
class Correction:
    """Une correction détectée."""
    ancien_fait: str = ""
    nouveau_fait: str = ""
    confidence: float = 0.0
    source_line: int = 0
    contexte: str = ""
    segment_id: Optional[int] = None


@dataclass
class RectificationResult:
    """Résultat du module Rectification."""
    corrections_detectees: int = 0
    segments_rectifies: int = 0
    liens_crees: int = 0
    mandats_executes: int = 0
    corrections: List[Correction] = field(default_factory=list)
    erreurs: List[str] = field(default_factory=list)


class Rectification:
    """
    Module de Rectification - Nettoyage des erreurs factuelles.
    
    Détecte les corrections explicites dans les conversations
    et marque les anciennes erreurs dans la base.
    """
    
    def __init__(self, config, sbire: Sbire, api_key: str):
        """
        Initialise le module Rectification.
        
        Args:
            config: MnemosyneConfig
            sbire: Instance du Sbire pour l'exécution
            api_key: Clé API Gemini
        """
        self.config = config
        self.sbire = sbire
        self.client = genai.Client(api_key=api_key)
        self.result = RectificationResult()
    
    def process(self, content: str) -> Dict[str, Any]:
        """
        Traite le contenu pour détecter et rectifier les erreurs.
        
        Args:
            content: Contenu du fichier tokenisé
            
        Returns:
            Dictionnaire avec les résultats
        """
        # Phase 1: Détecter les corrections
        print(f"   🔍 Détection des corrections...")
        corrections = self._detect_corrections(content)
        self.result.corrections_detectees = len(corrections)
        self.result.corrections = corrections
        
        print(f"      → {len(corrections)} correction(s) détectée(s)")
        
        if not corrections:
            return self._to_dict()
        
        # Phase 2: Pour chaque correction, chercher et rectifier
        print(f"   🔧 Recherche des erreurs passées...")
        
        for i, corr in enumerate(corrections, 1):
            if self.config.verbose:
                print(f"\n      [{i}/{len(corrections)}] '{corr.nouveau_fait[:40]}...'")
            
            self._process_correction(corr)
        
        return self._to_dict()
    
    def _detect_corrections(self, content: str) -> List[Correction]:
        """
        Détecte les corrections dans le texte.
        
        Utilise d'abord les patterns regex (gratuit),
        puis Gemini pour les cas subtils si nécessaire.
        """
        corrections = []
        lines = content.split('\n')
        
        # Étape 1: Patterns regex (rapide et gratuit)
        for line_num, line in enumerate(lines, 1):
            for pattern in CORRECTION_PATTERNS:
                match = re.search(pattern, line, re.IGNORECASE)
                if match:
                    groups = match.groups()
                    
                    if len(groups) >= 2:
                        # Pattern avec ancien ET nouveau
                        ancien = groups[0].strip()
                        nouveau = groups[1].strip()
                    else:
                        # Pattern avec seulement le nouveau
                        ancien = ""
                        nouveau = groups[0].strip() if groups else ""
                    
                    if nouveau and len(nouveau) > 3:
                        corrections.append(Correction(
                            ancien_fait=ancien,
                            nouveau_fait=nouveau,
                            source_line=line_num,
                            contexte=line[:300],
                            confidence=0.7
                        ))
        
        # Dédupliquer par nouveau_fait
        seen = set()
        unique_corrections = []
        for c in corrections:
            key = c.nouveau_fait.lower()[:50]
            if key not in seen:
                seen.add(key)
                unique_corrections.append(c)
        
        # Étape 2: Gemini pour cas subtils (si peu de résultats et fichier conséquent)
        if len(unique_corrections) < 3 and len(content) > 2000:
            gemini_corrections = self._detect_with_gemini(content[:8000])
            
            # Ajouter les nouvelles
            for gc in gemini_corrections:
                key = gc.nouveau_fait.lower()[:50]
                if key not in seen:
                    seen.add(key)
                    unique_corrections.append(gc)
        
        return unique_corrections
    
    def _detect_with_gemini(self, content: str) -> List[Correction]:
        """Utilise Gemini pour détecter les corrections subtiles."""
        
        system_prompt = """Tu es Mnémosyne, l'agent de cohérence mémorielle de MOSS.

MISSION: Identifier les CORRECTIONS FACTUELLES explicites dans ce texte.

Une correction = l'humain rectifie une ERREUR factuelle:
- "Non, c'est le 9 mai, pas décembre"
- "La vraie date c'est..."
- "Tu te trompes, c'est X pas Y"

⚠️ IMPORTANT:
- NE CONFONDS PAS correction et évolution de pensée
- Correction = ERREUR rectifiée
- Évolution = changement d'avis (pas une erreur)

Réponds UNIQUEMENT en JSON valide:
{
  "corrections": [
    {
      "ancien_fait": "ce qui était faux (si connu)",
      "nouveau_fait": "ce qui est vrai",
      "confidence": 0.0-1.0,
      "contexte": "extrait du texte"
    }
  ]
}

Si AUCUNE correction: {"corrections": []}"""

        try:
            response = self.client.models.generate_content(
                model=self.config.model,
                contents=f"Analyse ce texte:\n\n{content}",
                config=types.GenerateContentConfig(
                    system_instruction=system_prompt,
                    temperature=0.0,
                    max_output_tokens=2048
                )
            )
            
            # Extraire le texte
            text = self._extract_text(response)
            
            # Parser le JSON
            return self._parse_corrections_json(text)
            
        except Exception as e:
            if self.config.verbose:
                print(f"      ⚠️ Erreur Gemini: {e}")
            self.result.erreurs.append(f"Gemini detect: {e}")
            return []
    
    def _process_correction(self, correction: Correction):
        """
        Traite une correction: cherche les erreurs passées et les rectifie.
        """
        # Générer le premier mandat
        mandat = self._generate_mandat(correction)
        all_results = []
        
        # Boucle de recherche avec persévérance bornée
        for iteration in range(1, self.config.max_iterations + 1):
            mandat.iteration = iteration
            
            results = self.sbire.execute(mandat)
            all_results.extend(results)
            self.result.mandats_executes += 1
            
            if self.config.verbose:
                print(f"         Iter {iteration}: {len(results)} résultat(s)")
            
            # Conditions d'arrêt
            if len(all_results) >= 20:
                break
            if not results and iteration > 2:
                break
            
            # Raffiner le mandat si pas assez de résultats
            if len(results) < 5:
                mandat = self._refine_mandat(mandat, results, correction)
        
        # Analyser et rectifier
        if all_results:
            self._rectify_errors(correction, all_results)
    
    def _generate_mandat(self, correction: Correction) -> Mandat:
        """Génère le premier mandat de recherche."""
        
        # Extraire les mots-clés significatifs
        text = correction.nouveau_fait + " " + correction.ancien_fait
        keywords = re.findall(r'\b\w{4,}\b', text.lower())
        
        # Filtrer les mots vides
        stopwords = {'est', 'sont', 'était', 'c\'est', 'cette', 'pour', 'dans', 'avec', 'plus', 'fait'}
        keywords = [k for k in keywords if k not in stopwords]
        
        if keywords:
            return Mandat(
                type='sql',
                query=keywords[0],
                context=f"Cherche erreurs sur: {correction.nouveau_fait[:50]}"
            )
        else:
            # Fallback: grep sur le contexte
            return Mandat(
                type='grep',
                pattern=correction.nouveau_fait[:30].replace(' ', '\\s+'),
                context=f"Cherche: {correction.nouveau_fait[:50]}"
            )
    
    def _refine_mandat(self, old_mandat: Mandat, results: List[Dict], 
                       correction: Correction) -> Mandat:
        """Raffine le mandat pour la prochaine itération."""
        
        # Si SQL n'a rien donné, essayer Word2Vec
        if old_mandat.type == 'sql' and not results:
            return Mandat(
                type='word2vec',
                query=old_mandat.query,
                context=old_mandat.context,
                iteration=old_mandat.iteration + 1
            )
        
        # Si Word2Vec n'a rien donné, essayer grep
        if old_mandat.type == 'word2vec' and not results:
            keywords = re.findall(r'\b\w{3,}\b', correction.nouveau_fait.lower())
            if keywords:
                return Mandat(
                    type='grep',
                    pattern='|'.join(keywords[:3]),
                    context=old_mandat.context,
                    iteration=old_mandat.iteration + 1
                )
        
        # Sinon, essayer avec l'ancien fait
        if correction.ancien_fait and old_mandat.iteration < 5:
            return Mandat(
                type='sql',
                query=correction.ancien_fait.split()[0] if correction.ancien_fait.split() else old_mandat.query,
                context=old_mandat.context,
                iteration=old_mandat.iteration + 1
            )
        
        return old_mandat
    
    def _rectify_errors(self, correction: Correction, results: List[Dict]):
        """Analyse les résultats et rectifie les erreurs."""
        
        # Filtrer les résultats déjà rectifiés
        candidates = [r for r in results if r.get('statut_verite', 0) != -1]
        
        if not candidates:
            if self.config.verbose:
                print(f"         Aucun candidat à rectifier")
            return
        
        # Demander à Gemini d'identifier les contradictions
        contradictions = self._find_contradictions(correction, candidates[:20])
        
        if self.config.verbose:
            print(f"         → {len(contradictions)} contradiction(s) identifiée(s)")
        
        # Appliquer les rectifications
        for segment_id in contradictions:
            if self.config.dry_run:
                print(f"         🔍 [DRY-RUN] Marquerait segment {segment_id}")
            else:
                if self.sbire.update_statut_verite(segment_id, -1):
                    self.result.segments_rectifies += 1
                    
                    # Créer le lien CORRIGE_PAR si on a l'ID source
                    if correction.segment_id:
                        if self.sbire.insert_edge(
                            segment_id,
                            correction.segment_id,
                            "CORRIGE_PAR",
                            {"raison": correction.nouveau_fait[:100]}
                        ):
                            self.result.liens_crees += 1
    
    def _find_contradictions(self, correction: Correction, 
                            candidates: List[Dict]) -> List[int]:
        """Utilise Gemini pour identifier les segments contradictoires."""
        
        # Préparer le contexte
        segments_text = "\n".join([
            f"[ID:{c.get('id', '?')}] {c.get('resume_texte', '')[:200]}"
            for c in candidates
        ])
        
        prompt = f"""FAIT ÉTABLI: "{correction.nouveau_fait}"

Voici des segments de mémoire. Lesquels CONTREDISENT ce fait?
(Contradiction = affirmer quelque chose de FAUX, pas juste différent)

{segments_text}

Réponds UNIQUEMENT avec les IDs des segments contradictoires, séparés par des virgules.
Si aucun: "AUCUN"
Exemple: 12345, 67890"""

        try:
            response = self.client.models.generate_content(
                model=self.config.model,
                contents=prompt,
                config=types.GenerateContentConfig(
                    temperature=0.0,
                    max_output_tokens=500
                )
            )
            
            text = self._extract_text(response)
            
            if "AUCUN" in text.upper():
                return []
            
            # Parser les IDs
            ids = []
            for match in re.findall(r'\d+', text):
                try:
                    segment_id = int(match)
                    # Vérifier que l'ID est dans nos candidats
                    if any(c.get('id') == segment_id for c in candidates):
                        ids.append(segment_id)
                except ValueError:
                    continue
            
            return ids
            
        except Exception as e:
            if self.config.verbose:
                print(f"         ⚠️ Erreur Gemini contradictions: {e}")
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
    
    def _parse_corrections_json(self, text: str) -> List[Correction]:
        """Parse le JSON de corrections retourné par Gemini."""
        try:
            # Nettoyer le markdown
            clean = text.strip()
            if clean.startswith("```"):
                clean = clean.split("```")[1]
                if clean.startswith("json"):
                    clean = clean[4:]
                clean = clean.strip()
            
            data = json.loads(clean)
            
            corrections = []
            for c in data.get("corrections", []):
                if c.get("nouveau_fait"):
                    corrections.append(Correction(
                        ancien_fait=c.get("ancien_fait", ""),
                        nouveau_fait=c.get("nouveau_fait", ""),
                        confidence=c.get("confidence", 0.5),
                        contexte=c.get("contexte", "")
                    ))
            
            return corrections
            
        except json.JSONDecodeError:
            return []
    
    def _to_dict(self) -> Dict[str, Any]:
        """Convertit le résultat en dictionnaire."""
        return {
            "corrections_detectees": self.result.corrections_detectees,
            "segments_rectifies": self.result.segments_rectifies,
            "liens_crees": self.result.liens_crees,
            "mandats_executes": self.result.mandats_executes,
            "erreurs": self.result.erreurs,
            "details": [
                {
                    "nouveau_fait": c.nouveau_fait,
                    "ancien_fait": c.ancien_fait,
                    "confidence": c.confidence
                }
                for c in self.result.corrections
            ]
        }
